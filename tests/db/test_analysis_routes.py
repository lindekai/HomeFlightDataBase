import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from synthetic.routes import (
    LOCAL,
    ONMID,
    ONORD,
    PROCEDURES_FILE,
    TEAST,
    THR_09,
    THR_27,
    TWEST,
    WNMID,
    WNORD,
    WSMID,
    WSUED,
    fly,
)
from synthetic.tracks import add_raw_file, insert_positions

from analysis.config import Config
from analysis.pipeline import rebuild, run_once, sync_procedures, sync_zones

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
NORTH = [THR_09, TWEST, WNMID, WNORD]
SOUTH = [THR_09, TWEST, WSMID, WSUED]
# Abflug, der vom WNORD1W abweicht und dabei die Zone streift
DETOUR = [THR_09, TWEST, (-23000.0, 6000.0), WNMID, WNORD]
ARRIVAL = [ONORD, ONMID, TEAST, THR_27]
ZONE_CENTER = (-26000.0, 6000.0)  # 8629 m neben WNORD1W, Radius 5000 m


def zones_geojson():
    lat, lon = LOCAL.latlon(*ZONE_CENTER)
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {"name": "Testzone", "radius_m": 5000},
                }
            ],
        }
    )


@pytest.fixture
def cfg(db_dsns, tmp_path):
    zones = tmp_path / "geofences.geojson"
    zones.write_text(zones_geojson(), encoding="utf-8")
    c = Config(
        db_dsn=db_dsns["analysis"],
        ber_lat=50.0,
        ber_lon=10.0,
        zones_file=zones,
        procedures_file=PROCEDURES_FILE,
    )
    sync_zones(c, zones)
    sync_procedures(c, PROCEDURES_FILE)
    return c


def departure(route, minutes, icao):
    return fly(route, T0 + timedelta(minutes=minutes), icao24=icao, callsign=f"TST{icao[-3:]}")


def arrival(minutes, icao):
    return fly(
        ARRIVAL,
        T0 + timedelta(minutes=minutes),
        speed_kt=180,
        alt_ft=11000,
        vrate_fpm=-1000,
        icao24=icao,
        callsign=f"TST{icao[-3:]}",
    )


def scenario(dsn):
    for rows in (
        departure(NORTH, 0, "ff0101"),
        departure(NORTH, 5, "ff0102"),
        departure(SOUTH, 10, "ff0103"),
        departure(DETOUR, 15, "ff0104"),
        arrival(5, "ff0105"),
    ):
        insert_positions(dsn, rows)
    add_raw_file(dsn, T0, T0 + timedelta(hours=1))


ASSESSMENTS = """
SELECT f.icao24, a.role, a.direction, a.flight_sector, p.name, a.confidence, a.deviation,
       a.approach, a.review, a.review_reasons
FROM flight_assessments a JOIN flights f ON f.id = a.flight_id
LEFT JOIN procedures p ON p.id = a.procedure_id ORDER BY f.icao24
"""


def q(dsn, sql, params=None):
    with psycopg.connect(dsn) as c:
        return c.execute(sql, params).fetchall()


def test_direction_assignment_and_review(db_dsns, cfg):
    scenario(db_dsns["admin"])

    result = run_once(cfg)

    assert (result.flights, result.assessments, result.skipped) == (5, 5, 0)
    assert q(
        db_dsns["reader"],
        "SELECT window_start, direction, n_flights, share FROM" " operating_directions",
    ) == [(T0, "west", 5, 1.0)]
    reasons = [
        "Abweichung",
        "Annäherung",
        "Sicherheit hoch",
        "Datenqualität ausreichend",
        "relevanter Überflug",
    ]
    assert q(db_dsns["reader"], ASSESSMENTS) == [
        (
            "ff0101",
            "departure",
            "west",
            "NW",
            "WNORD1W",
            "high",
            False,
            False,
            False,
            ["Sicherheit hoch", "Datenqualität ausreichend"],
        ),
        (
            "ff0102",
            "departure",
            "west",
            "NW",
            "WNORD1W",
            "high",
            False,
            False,
            False,
            ["Sicherheit hoch", "Datenqualität ausreichend"],
        ),
        (
            "ff0103",
            "departure",
            "west",
            "SW",
            "WSUED1W",
            "high",
            False,
            False,
            False,
            ["Sicherheit hoch", "Datenqualität ausreichend"],
        ),
        ("ff0104", "departure", "west", "NW", "WNORD1W", "high", True, True, True, reasons),
        (
            "ff0105",
            "arrival",
            "west",
            "NO",
            "ONORD1W",
            "high",
            False,
            False,
            False,
            ["Sicherheit hoch", "Datenqualität ausreichend"],
        ),
    ]
    ((max_dev, outside_s, min_ref, proc_ref, gap),) = q(
        db_dsns["reader"],
        "SELECT round(max_dev_m), round(outside_s), round(min_dist_ref_m),"
        " round(proc_dist_ref_m), max_position_gap_s FROM flight_assessments a"
        " JOIN flights f ON f.id = a.flight_id WHERE f.icao24 = 'ff0104'",
    )
    # Umweg-Wegpunkt 5687 m neben der Linie; nächste Position 5658 m; 15,9 km außerhalb
    assert (max_dev, outside_s, min_ref, proc_ref, gap) == (5658, 123, 3016, 8629, 1.0)


def test_late_flight_changes_direction_and_assessment(db_dsns, cfg):
    insert_positions(db_dsns["admin"], departure(NORTH, 0, "ff0101"))
    insert_positions(db_dsns["admin"], departure(SOUTH, 0, "ff0102"))
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    first = run_once(cfg)
    assert q(db_dsns["reader"], "SELECT direction, n_flights FROM operating_directions") == [
        ("unknown", 2)
    ]
    assert {r[5] for r in q(db_dsns["reader"], ASSESSMENTS)} == {"medium"}

    # Nachlieferung im selben Fenster; die ersten Flüge bleiben bestehen (enden vor 14:08).
    insert_positions(db_dsns["admin"], departure(NORTH, 20, "ff0103"))
    add_raw_file(db_dsns["admin"], T0 + timedelta(minutes=20), T0 + timedelta(minutes=30))
    second = run_once(cfg)

    assert second.window_from == T0 + timedelta(minutes=18)
    assert q(db_dsns["reader"], "SELECT direction, n_flights FROM operating_directions") == [
        ("west", 3)
    ]
    rows = q(
        db_dsns["reader"],
        "SELECT f.icao24, f.analysis_run_id, a.run_id, a.confidence FROM flight_assessments a"
        " JOIN flights f ON f.id = a.flight_id ORDER BY 1",
    )
    assert rows == [
        ("ff0101", first.run_id, second.run_id, "high"),
        ("ff0102", first.run_id, second.run_id, "high"),
        ("ff0103", second.run_id, second.run_id, "high"),
    ]


def test_rebuild_reproduces_assessments(db_dsns, cfg):
    scenario(db_dsns["admin"])
    run_once(cfg)
    directions = "SELECT window_start, direction, n_flights, share FROM operating_directions"
    before = q(db_dsns["reader"], ASSESSMENTS), q(db_dsns["reader"], directions)

    result = rebuild(cfg, T0 - timedelta(days=1), T0 + timedelta(days=1))

    assert result.assessments == 5
    assert (q(db_dsns["reader"], ASSESSMENTS), q(db_dsns["reader"], directions)) == before


def test_assessments_follow_flight_deletion(db_dsns, cfg):
    scenario(db_dsns["admin"])
    run_once(cfg)
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        c.execute("DELETE FROM flights")
    assert q(db_dsns["reader"], "SELECT count(*) FROM flight_assessments") == [(0,)]


def test_procedure_must_be_valid_at_flight_date(db_dsns, cfg, tmp_path):
    expired = tmp_path / "procedures.yaml"
    expired.write_text(
        PROCEDURES_FILE.read_text("utf-8").replace("valid_to: null", "valid_to: 2026-11-09"),
        encoding="utf-8",
    )
    sync_procedures(cfg, expired)
    scenario(db_dsns["admin"])
    run_once(cfg)
    assert {(r[4], r[5]) for r in q(db_dsns["reader"], ASSESSMENTS)} == {(None, "none")}


def test_without_procedures_file_step_is_skipped(db_dsns, cfg, caplog):
    scenario(db_dsns["admin"])
    no_file = Config(**{**cfg.__dict__, "procedures_file": None})
    with caplog.at_level("WARNING", logger="analysis"):
        result = run_once(no_file)
    assert (result.flights, result.assessments) == (5, 0)
    assert any("Routenvergleich übersprungen" in r.message for r in caplog.records)
    assert q(db_dsns["reader"], "SELECT count(*) FROM flight_assessments") == [(0,)]


def test_altitude_limit_uses_stored_altitudes(db_dsns, cfg):
    insert_positions(db_dsns["admin"], departure(NORTH, 0, "ff0101"))
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    limited = Config(**{**cfg.__dict__, "route_max_alt_ft": 3000})
    run_once(limited)
    # 500 ft + 2000 ft/min: 3000 ft nach 75 s
    assert q(db_dsns["reader"], "SELECT eval_from, eval_to FROM flight_assessments") == [
        (T0, T0 + timedelta(seconds=75))
    ]


def test_invalid_file_keeps_previous_version(db_dsns, cfg, tmp_path, monkeypatch):
    from analysis import cli

    bad = tmp_path / "procedures.yaml"
    bad.write_text(PROCEDURES_FILE.read_text("utf-8").replace("route: [TWEST,", "route: [XXXXX,"))
    for k, v in {
        "ANALYSIS_DB_DSN": db_dsns["analysis"],
        "ANALYSIS_BER_LAT": "50",
        "ANALYSIS_BER_LON": "10",
    }.items():
        monkeypatch.setenv(k, v)

    assert cli.main(["procedures", str(bad)]) == 1
    assert q(db_dsns["reader"], "SELECT count(*) FROM procedures WHERE superseded_at IS NULL") == [
        (8,)
    ]


def icao_of(conn, flight_id):
    return conn.execute("SELECT icao24 FROM flights WHERE id = %s", (flight_id,)).fetchone()[0]


def test_failing_role_keeps_flights_and_events(db_dsns, cfg, monkeypatch):
    from analysis import routes

    original = routes.record_role

    def record_role(conn, run_id, flight_id, points, ctx, c):
        if icao_of(conn, flight_id) == "ff0104":
            raise ValueError("Rolle kaputt")
        return original(conn, run_id, flight_id, points, ctx, c)

    monkeypatch.setattr(routes, "record_role", record_role)
    scenario(db_dsns["admin"])

    result = run_once(cfg)

    assert (result.flights, result.assessments, result.skipped) == (5, 4, 1)
    assert q(
        db_dsns["reader"],
        "SELECT count(*) FROM overflight_events e JOIN flights f ON f.id = e.flight_id"
        " WHERE f.icao24 = 'ff0104'",
    ) == [(1,)]
    assert q(
        db_dsns["reader"],
        "SELECT count(*) FROM flight_assessments a JOIN flights f ON f.id = a.flight_id"
        " WHERE f.icao24 = 'ff0104'",
    ) == [(0,)]


def test_failing_route_step_keeps_run(db_dsns, cfg, monkeypatch, caplog):
    from analysis import routes

    def update_directions(*args):
        raise ValueError("Richtung kaputt")

    monkeypatch.setattr(routes, "update_directions", update_directions)
    scenario(db_dsns["admin"])

    with caplog.at_level("WARNING", logger="analysis"):
        result = run_once(cfg)

    assert (result.flights, result.events, result.assessments) == (5, 1, 0)
    assert q(db_dsns["reader"], "SELECT status FROM analysis_runs") == [("ok",)]
    assert q(db_dsns["reader"], "SELECT count(*) FROM overflight_events") == [(1,)]
    assert any("Routenvergleich übersprungen" in r.message for r in caplog.records)


def test_failed_assessment_is_retried_next_run(db_dsns, cfg, monkeypatch):
    from analysis import routes

    original = routes.assess
    failed = []

    def assess(conn, run_id, flight_id, ctx, c):
        if not failed and icao_of(conn, flight_id) == "ff0104":
            failed.append(flight_id)
            raise ValueError("Bewertung kaputt")
        return original(conn, run_id, flight_id, ctx, c)

    monkeypatch.setattr(routes, "assess", assess)
    scenario(db_dsns["admin"])
    first = run_once(cfg)
    assert (first.assessments, first.skipped) == (4, 1)

    # Nächster Lauf mit einem neuen Flug in einem späteren Fenster
    insert_positions(db_dsns["admin"], departure(NORTH, 70, "ff0106"))
    add_raw_file(db_dsns["admin"], T0 + timedelta(hours=1), T0 + timedelta(minutes=90))
    second = run_once(cfg)

    assert (second.assessments, second.skipped) == (2, 0)
    assert q(
        db_dsns["reader"],
        "SELECT a.run_id, a.direction, a.confidence FROM flight_assessments a"
        " JOIN flights f ON f.id = a.flight_id WHERE f.icao24 = 'ff0104'",
    ) == [(second.run_id, "west", "high")]


def test_dashboard_queries_show_review(db_dsns, cfg):
    import build_dashboards
    from dashboard_sql import substitute

    scenario(db_dsns["admin"])
    run_once(cfg)
    panels = {p["title"]: p for p in build_dashboards.flugrouten()["panels"]}
    with psycopg.connect(db_dsns["reader"]) as c:

        def rows(title, ref=0):
            return c.execute(substitute(panels[title]["targets"][ref]["rawSql"])).fetchall()

        assert rows("Prüffälle (E)") == [(1,)]
        assert rows("Bewertbar (Sicherheit ≥ mittel)") == [(100,)]
        (review,) = rows("Prüffälle")
        assert review[1:4] == ("TST104", "SID WNORD1W", "high")
        assert review[6] == "Abweichung, Annäherung"
        assert rows("Je Verfahren")[0][:3] == ("SID WNORD1W", 3, 33)
        assert len(rows("Ideallinien, Korridor, Spuren", 1)) > 100  # Korridorrand
        spur = {p["title"]: p for p in build_dashboards.flugspur()["panels"]}["Spur"]
        flight_id = str(review[8])
        ideal = c.execute(substitute(spur["targets"][1]["rawSql"], flight_id=flight_id))
        assert len(ideal.fetchall()) > 100
