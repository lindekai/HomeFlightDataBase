import psycopg
import pytest
from conftest import MIGRATIONS

from ingest.db import migrate

pytestmark = pytest.mark.db


def test_migrate_is_idempotent(db_dsns):
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        assert migrate(c, MIGRATIONS) == []
        versions = [r[0] for r in c.execute("SELECT version FROM schema_migrations")]
        assert versions == ["001_erfassung.sql", "002_analyse.sql"]


def test_positions_is_partitioned(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c:
        kind = c.execute("SELECT relkind FROM pg_class WHERE relname = 'positions'").fetchone()
        assert kind == ("p",)


def test_reader_cannot_write(db_dsns):
    with psycopg.connect(db_dsns["reader"]) as c:
        assert c.execute("SELECT count(*) FROM ingest_status").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO receivers (id, label) VALUES ('X', 'x')")


def test_ingest_can_write_receivers(db_dsns):
    with psycopg.connect(db_dsns["ingest"]) as c:
        c.execute("INSERT INTO receivers (id, label) VALUES ('TEST', 'Test')")
        c.commit()


def test_analysis_role_reads_positions_but_cannot_write_them(db_dsns):
    with psycopg.connect(db_dsns["analysis"]) as c:
        assert c.execute("SELECT count(*) FROM positions").fetchone() == (0,)
        c.execute(
            "INSERT INTO analysis_runs (kind, algo_version, params, status)"
            " VALUES ('incremental', 'test', '{}', 'running')"
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "INSERT INTO positions (ts, receiver_id, icao24, geom, raw_file_id)"
                " VALUES (now(), 'TEST', 'ff0001', ST_MakePoint(10, 50), 0)"
            )


def test_reader_reads_analysis_views(db_dsns):
    with psycopg.connect(db_dsns["reader"]) as c:
        for view in ("overflights_daily", "data_coverage_daily", "overflight_events"):
            c.execute(f"SELECT * FROM {view} LIMIT 1")


def test_circle_needs_radius(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute(
            "INSERT INTO geofences (name, kind, geom, ref_point) VALUES ('x', 'circle',"
            " ST_Multi(ST_Buffer(ST_MakePoint(10, 50), 0.01))::geometry(MultiPolygon, 4326),"
            " ST_SetSRID(ST_MakePoint(10, 50), 4326))"
        )


def test_coverage_view_subtracts_gaps(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c:
        c.execute("INSERT INTO receivers (id, label) VALUES ('TEST', 'Test')")
        raw_id = c.execute(
            "INSERT INTO raw_files (receiver_id, path, sha256, size_bytes, period_start,"
            " period_end, status, ingest_version) VALUES ('TEST', 'TEST/a', repeat('a', 64), 1,"
            " '2026-11-09T14:00:00Z', '2026-11-09T16:00:00Z', 'ingested', 'test') RETURNING id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO reception_gaps (receiver_id, gap_start, gap_end, reason, raw_file_id)"
            " VALUES ('TEST', '2026-11-09T15:00:00Z', '2026-11-09T15:10:00Z', 'no_data', %s)",
            (raw_id,),
        )
        row = c.execute(
            "SELECT recorded_s, gap_s, day_s FROM data_coverage_daily WHERE day = '2026-11-09'"
        ).fetchone()
    assert row == (7200, 600, 86400)


def test_coverage_view_counts_gaps_only_inside_files(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c:
        c.execute("INSERT INTO receivers (id, label) VALUES ('TEST', 'Test')")
        ids = [
            c.execute(
                "INSERT INTO raw_files (receiver_id, path, sha256, size_bytes, period_start,"
                " period_end, status, ingest_version) VALUES ('TEST', %s, repeat(%s, 64), 1,"
                " %s, %s, 'ingested', 'test') RETURNING id",
                (f"TEST/{n}", n, start, end),
            ).fetchone()[0]
            for n, start, end in (
                ("a", "2026-11-09T06:00:00Z", "2026-11-09T08:00:00Z"),
                ("b", "2026-11-09T10:00:00Z", "2026-11-09T12:00:00Z"),
            )
        ]
        for start, end, reason in (
            # Neustart-Lücke zwischen den Dateien: liegt außerhalb jedes Dateizeitraums.
            ("2026-11-09T08:00:00Z", "2026-11-09T10:00:00Z", "recorder_restart"),
            # Überlappende Lücken zählen einmal (15 min).
            ("2026-11-09T11:00:00Z", "2026-11-09T11:10:00Z", "no_data"),
            ("2026-11-09T11:05:00Z", "2026-11-09T11:15:00Z", "stale"),
            # Ragt über das Dateiende hinaus: nur 10 min zählen.
            ("2026-11-09T11:50:00Z", "2026-11-09T12:30:00Z", "no_data"),
        ):
            c.execute(
                "INSERT INTO reception_gaps (receiver_id, gap_start, gap_end, reason, raw_file_id)"
                " VALUES ('TEST', %s, %s, %s, %s)",
                (start, end, reason, ids[1]),
            )
        row = c.execute(
            "SELECT recorded_s, gap_s, day_s FROM data_coverage_daily WHERE day = '2026-11-09'"
        ).fetchone()
    assert row == (14400, 1500, 86400)
