from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from synthetic.tracks import add_raw_file, insert_positions, offset, straight

from analysis.config import Config
from analysis.pipeline import NoZones, compute_window, rebuild, run_once, sync_zones

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
ZONES = (
    '{"type": "FeatureCollection", "features": [{"type": "Feature", "geometry":'
    ' {"type": "Point", "coordinates": [10.0, 50.0]}, "properties": {"name": "Testzone",'
    ' "radius_m": 5000}}]}'
)


@pytest.fixture
def cfg(db_dsns, tmp_path):
    zones = tmp_path / "geofences.geojson"
    zones.write_text(ZONES, encoding="utf-8")
    c = Config(db_dsn=db_dsns["analysis"], ber_lat=49.0, ber_lon=8.0, zones_file=zones)
    sync_zones(c, zones)
    return c


def east_track(start=T0, icao="ff0001", n=400):
    lat, lon = offset(50.0, 10.0, 2000, -20000)
    return straight(start, lat, lon, 90, 200, n, icao24=icao)


def q(dsn, sql):
    with psycopg.connect(dsn) as c:
        return c.execute(sql).fetchall()


def test_first_run_builds_flight_and_event(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))

    result = run_once(cfg)

    assert (result.kind, result.flights, result.events, result.skipped) == ("incremental", 1, 1, 0)
    assert result.window_to == T0 + timedelta(hours=1) - timedelta(seconds=120)
    (row,) = q(
        db_dsns["reader"],
        "SELECT category, relevant, heading_sector, in_reception_gap, round(duration_s)"
        " FROM overflight_events",
    )
    assert row == ("overflight", True, "O", False, 89)
    assert q(db_dsns["reader"], "SELECT status, kind FROM analysis_runs") == [("ok", "incremental")]


def test_nothing_new_creates_no_run(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    run_once(cfg)
    assert run_once(cfg) is None
    assert len(q(db_dsns["reader"], "SELECT id FROM analysis_runs")) == 1


def test_open_flight_is_extended_without_duplicates(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(minutes=5))  # Fenster bis 180 s
    first = run_once(cfg)
    assert first.window_to == T0 + timedelta(seconds=180)
    add_raw_file(db_dsns["admin"], T0 + timedelta(minutes=5), T0 + timedelta(minutes=10))

    run_once(cfg)

    assert q(db_dsns["reader"], "SELECT count(*) FROM flights") == [(1,)]
    ((n, exit_s),) = q(
        db_dsns["reader"],
        "SELECT count(*), round(extract(epoch FROM max(exit_ts) - '2026-11-09T14:00:00Z'))"
        " FROM overflight_events",
    )
    assert (n, exit_s) == (1, 239)


def test_late_file_triggers_recompute(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track(T0 + timedelta(hours=1), icao="ff0001"))
    add_raw_file(db_dsns["admin"], T0 + timedelta(hours=1), T0 + timedelta(hours=2))
    run_once(cfg)

    insert_positions(db_dsns["admin"], east_track(T0 + timedelta(minutes=10), icao="ff0002"))
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    result = run_once(cfg)

    assert result.window_from == T0 - timedelta(seconds=120)
    assert q(db_dsns["reader"], "SELECT icao24, count(*) FROM flights GROUP BY 1 ORDER BY 1") == [
        ("ff0001", 1),
        ("ff0002", 1),
    ]


def test_pending_file_caps_window(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    add_raw_file(db_dsns["admin"], T0 + timedelta(minutes=30), T0, status="registered")
    with psycopg.connect(cfg.db_dsn) as c:
        _, window_to = compute_window(c, cfg)
    assert window_to == T0 + timedelta(minutes=30) - timedelta(seconds=120)


def test_rebuild_reproduces_events(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    run_once(cfg)
    sql = (
        "SELECT f.icao24, e.entry_ts, e.exit_ts, round(e.min_dist_m), e.category"
        " FROM overflight_events e JOIN flights f ON f.id = e.flight_id ORDER BY 1, 2"
    )
    before = q(db_dsns["reader"], sql)

    result = rebuild(cfg, T0 - timedelta(days=1), T0 + timedelta(days=1))

    assert result.kind == "rebuild" and result.events == 1
    assert q(db_dsns["reader"], sql) == before
    assert q(db_dsns["reader"], "SELECT count(*) FROM flights") == [(1,)]


def test_missing_zones_marks_run_failed(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        c.execute("UPDATE geofences SET valid_to = now()")

    with pytest.raises(NoZones):
        run_once(cfg)

    ((status, error),) = q(db_dsns["reader"], "SELECT status, error FROM analysis_runs")
    assert status == "failed" and "Zone" in error
    assert q(db_dsns["reader"], "SELECT count(*) FROM flights") == [(0,)]


def test_error_in_one_aircraft_is_isolated(db_dsns, cfg, monkeypatch):
    import analysis.pipeline as pipeline

    insert_positions(db_dsns["admin"], east_track(icao="ff0001"))
    insert_positions(db_dsns["admin"], east_track(icao="ff0002"))
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    original = pipeline.segment

    def failing(icao, points, **kw):
        if icao == "ff0001":
            raise ValueError("kaputte Daten")
        return original(icao, points, **kw)

    monkeypatch.setattr(pipeline, "segment", failing)

    result = run_once(cfg)

    assert (result.flights, result.events, result.skipped) == (1, 1, 1)
    assert q(db_dsns["reader"], "SELECT icao24 FROM flights") == [("ff0002",)]
    assert q(db_dsns["reader"], "SELECT status FROM analysis_runs") == [("ok",)]


def test_pending_file_capping_window_is_logged(db_dsns, cfg, caplog):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    add_raw_file(db_dsns["admin"], T0 + timedelta(minutes=30), T0, status="failed")
    with caplog.at_level("WARNING", logger="analysis"), psycopg.connect(cfg.db_dsn) as c:
        compute_window(c, cfg)
    (rec,) = (r for r in caplog.records if r.levelname == "WARNING")
    assert rec.path == "TEST/2026/11/09/20261109T143000Z.ndjson.gz"
    assert rec.status == "failed"
    assert rec.file_start == T0 + timedelta(minutes=30)
    assert rec.waiting_s >= 0


def test_no_warning_when_pending_file_does_not_cap(db_dsns, cfg, caplog):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    add_raw_file(db_dsns["admin"], T0 + timedelta(hours=2), T0, status="registered")
    with caplog.at_level("WARNING", logger="analysis"), psycopg.connect(cfg.db_dsn) as c:
        compute_window(c, cfg)
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []


@pytest.fixture
def health_env(db_dsns, monkeypatch, tmp_path):
    hb = tmp_path / "hb"
    hb.write_text("")
    for k, v in {
        "ANALYSIS_DB_DSN": db_dsns["analysis"],
        "ANALYSIS_BER_LAT": "49",
        "ANALYSIS_BER_LON": "8",
        "ANALYSIS_HEARTBEAT_FILE": str(hb),
        "ANALYSIS_MAX_LAG_S": "3600",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ANALYSIS_ZONES_FILE", raising=False)


def test_health_ok_after_regular_run(db_dsns, cfg, health_env):
    from analysis import cli

    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    run_once(cfg)
    assert cli.main(["health"]) == 0


def test_health_fails_when_failed_file_stalls_watermark(db_dsns, cfg, health_env):
    from analysis import cli

    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    run_once(cfg)
    # Defekte Datei direkt danach; weitere Stunden kommen an, das Fenster bleibt stehen.
    add_raw_file(db_dsns["admin"], T0 + timedelta(hours=1), T0, status="failed")
    add_raw_file(db_dsns["admin"], T0 + timedelta(hours=2), T0 + timedelta(hours=3))
    assert run_once(cfg) is None
    assert cli.main(["health"]) == 1


def test_health_ok_when_receiver_offline(db_dsns, cfg, health_env):
    from analysis import cli

    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    run_once(cfg)
    # Keine neueren Daten: das Wasserzeichen ist alt, aber das ist kein Fehler der Auswertung.
    assert cli.main(["health"]) == 0


def test_health_default_tolerates_fresh_hourly_file(db_dsns, cfg, health_env, monkeypatch):
    from analysis import cli

    # Standardwert statt der 3600 s aus health_env: eine gerade eingelesene Stundendatei vor dem
    # nächsten Lauf darf keinen Fehlalarm auslösen.
    monkeypatch.delenv("ANALYSIS_MAX_LAG_S")
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    run_once(cfg)
    add_raw_file(db_dsns["admin"], T0 + timedelta(hours=1), T0 + timedelta(hours=2))
    assert cli.main(["health"]) == 0
