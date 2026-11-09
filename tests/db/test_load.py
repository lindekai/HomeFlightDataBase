from datetime import UTC, datetime

import psycopg
import pytest
from synthetic.generator import aircraft, snapshot
from synthetic.rawfiles import line, write_raw_file

from ingest import db
from ingest.parse import parse_file

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
NOW = T0.timestamp()
PATH = "TEST/2026/11/09/20261109T140000Z.ndjson.gz"


@pytest.fixture
def conns(db_dsns):
    with (
        psycopg.connect(db_dsns["admin"], autocommit=True) as admin,
        psycopg.connect(db_dsns["ingest"], autocommit=True) as conn,
    ):
        yield admin, conn


def parsed_sample(tmp_path):
    snaps = [snapshot(NOW + i, [aircraft(lat=50.0 + i / 100)]) for i in range(5)]
    span = {"from": "2026-11-09T13:59:00.000Z", "to": "2026-11-09T13:59:30.000Z"}
    extra = [line("gap", T0, **span, reason="no_data"), line("status", T0, free_bytes=999)]
    return parse_file(write_raw_file(tmp_path, T0, snaps, extra=extra))


def register(conn, sha="a" * 64, path=PATH):
    db.ensure_receiver(conn, "TEST")
    return db.register_raw_file(
        conn,
        receiver_id="TEST",
        path=path,
        sha256=sha,
        size_bytes=1,
        partial=False,
        version="test",
    )


def test_ensure_partitions_creates_months_once(conns):
    admin, _ = conns
    start, end = datetime(2026, 12, 30, tzinfo=UTC), datetime(2027, 1, 2, tzinfo=UTC)
    assert db.ensure_partitions(admin, start, end) == ["positions_y2026m12", "positions_y2027m01"]
    assert db.ensure_partitions(admin, start, end) == []


def test_load_is_idempotent_and_complete(conns, tmp_path):
    admin, conn = conns
    parsed = parsed_sample(tmp_path)
    db.ensure_partitions(admin, T0, T0)
    raw_id, status = register(conn)
    assert status == "registered"

    assert db.load_parsed(conn, raw_id, parsed) == 5
    assert db.load_parsed(conn, raw_id, parsed) == 0

    row = conn.execute(
        "SELECT status, receiver_free_bytes, period_start FROM raw_files WHERE id = %s", (raw_id,)
    ).fetchone()
    assert row == ("ingested", 999, T0)
    assert conn.execute("SELECT count(*) FROM reception_gaps").fetchone() == (1,)
    lat = conn.execute("SELECT ST_Y(geom) FROM positions ORDER BY ts LIMIT 1").fetchone()[0]
    assert lat == pytest.approx(50.0)
    assert db.find_raw_file(conn, "a" * 64) == raw_id
    assert db.pending_files(conn) == []


def test_register_returns_existing(conns):
    _, conn = conns
    first = register(conn)
    assert register(conn) == first


def test_same_path_different_checksum_is_rejected(conns):
    _, conn = conns
    register(conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        register(conn, sha="b" * 64)


def test_aircraft_upsert_extends_range(conns, tmp_path):
    admin, conn = conns
    db.ensure_partitions(admin, T0, T0)
    later = datetime(2026, 11, 9, 15, 0, 0, tzinfo=UTC)
    a = parse_file(write_raw_file(tmp_path / "a", T0, [snapshot(NOW, [aircraft()])]))
    b_snap = [snapshot(later.timestamp(), [aircraft()])]
    b = parse_file(write_raw_file(tmp_path / "b", later, b_snap))
    db.load_parsed(conn, register(conn)[0], a)
    db.load_parsed(conn, register(conn, "c" * 64, "TEST/x2.ndjson.gz")[0], b)
    first, last = conn.execute(
        "SELECT first_seen, last_seen FROM aircraft WHERE icao24 = 'ff0001'"
    ).fetchone()
    assert last - first > (later - T0) * 0.9


def test_failed_and_delete(conns, tmp_path):
    admin, conn = conns
    parsed = parsed_sample(tmp_path)
    db.ensure_partitions(admin, T0, T0)
    raw_id, _ = register(conn)
    db.load_parsed(conn, raw_id, parsed)

    db.delete_file_data(conn, raw_id)
    assert conn.execute("SELECT count(*) FROM positions").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM reception_gaps").fetchone() == (0,)
    db.mark_failed(conn, raw_id, "Testfehler")
    assert db.pending_files(conn) == [(raw_id, PATH, "a" * 64)]


def test_status_view(conns, tmp_path):
    admin, conn = conns
    db.ensure_partitions(admin, T0, T0)
    db.load_parsed(conn, register(conn)[0], parsed_sample(tmp_path))
    row = conn.execute(
        "SELECT receiver_id, files_not_ingested, receiver_free_bytes FROM ingest_status"
    ).fetchone()
    assert row == ("TEST", 0, 999)
