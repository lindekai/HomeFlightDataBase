from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from conftest import MIGRATIONS
from synthetic.generator import aircraft, snapshot
from synthetic.rawfiles import write_raw_file

from ingest.checksum import sha256_file
from ingest.config import Config
from ingest.pipeline import rebuild, run_once

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)


def make_cfg(tmp_path, dsns, environment="test"):
    return Config(
        admin_dsn=dsns["admin"],
        ingest_dsn=dsns["ingest"],
        receiver_host="unused",
        receiver_user="unused",
        ssh_key_read=Path("/unused"),
        ssh_key_ack=Path("/unused"),
        work_dir=tmp_path / "work",
        archive_dir=tmp_path / "archive",
        migrations_dir=MIGRATIONS,
        environment=environment,
    )


def stage(cfg, start=T0, n=3):
    snaps = [snapshot(start.timestamp() + i, [aircraft(lat=50 + i / 100)]) for i in range(n)]
    return write_raw_file(cfg.staging_dir, start, snaps)


def count(dsn, query):
    with psycopg.connect(dsn) as c:
        return c.execute(query).fetchone()[0]


def test_ingests_archives_and_acks(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns)
    staged = stage(cfg)
    rel = staged.relative_to(cfg.staging_dir)

    (result,) = run_once(cfg, pull=False)

    assert (result.status, result.positions) == ("ingested", 3)
    archived = cfg.archive_dir / rel
    assert archived.exists() and archived.with_name(archived.name + ".sha256").exists()
    assert not staged.exists()
    ack = cfg.ack_dir / rel.parent / (rel.name + ".ack")
    assert ack.read_text().strip() == sha256_file(archived)
    assert count(db_dsns["admin"], "SELECT count(*) FROM positions") == 3
    assert cfg.heartbeat_file.exists()


def test_same_file_again_is_skipped(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns)
    staged = stage(cfg)
    content = staged.read_bytes(), staged.with_name(staged.name + ".sha256").read_bytes()
    run_once(cfg, pull=False)
    staged.write_bytes(content[0])
    staged.with_name(staged.name + ".sha256").write_bytes(content[1])

    (result,) = run_once(cfg, pull=False)

    assert result.status == "skipped"
    assert count(db_dsns["admin"], "SELECT count(*) FROM positions") == 3


def test_corrupt_file_goes_to_quarantine(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns)
    staged = stage(cfg)
    staged.write_bytes(staged.read_bytes() + b"x")
    (result,) = run_once(cfg, pull=False)
    assert result.status == "quarantined"
    assert (cfg.quarantine_dir / staged.relative_to(cfg.staging_dir)).exists()
    assert not list(cfg.ack_dir.rglob("*.ack"))


def test_production_quarantines_synthetic(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns, environment="production")
    stage(cfg)
    (result,) = run_once(cfg, pull=False)
    assert result.status == "quarantined"
    assert "synthetisch" in result.message
    assert count(db_dsns["admin"], "SELECT count(*) FROM raw_files") == 0


def test_rebuild_reloads_from_archive(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns)
    stage(cfg)
    run_once(cfg, pull=False)
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        c.execute("DELETE FROM positions WHERE ts > (SELECT min(ts) FROM positions)")

    results = rebuild(cfg, datetime(2026, 11, 9, tzinfo=UTC), datetime(2026, 11, 10, tzinfo=UTC))

    assert [r.status for r in results] == ["ingested"]
    assert count(db_dsns["admin"], "SELECT count(*) FROM positions") == 3
    assert count(db_dsns["admin"], "SELECT count(*) FROM raw_files") == 1
