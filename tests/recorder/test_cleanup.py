import os
from datetime import UTC, datetime
from pathlib import Path

from recorder.cleanup import cleanup, free_space

NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
DAY = 86400


def make(complete, acked, name, age_days, ack=True):
    gz = complete / "TEST/2026/11/09" / name
    gz.parent.mkdir(parents=True, exist_ok=True)
    gz.write_bytes(b"x")
    sidecar = gz.with_name(gz.name + ".sha256")
    sidecar.write_text("x")
    mtime = NOW.timestamp() - age_days * DAY
    os.utime(gz, (mtime, mtime))
    if ack:
        a = acked / "TEST/2026/11/09" / (name + ".ack")
        a.parent.mkdir(parents=True, exist_ok=True)
        a.write_text("x")
    return gz


def test_deletes_only_acked_and_old(tmp_path):
    complete, acked = tmp_path / "complete", tmp_path / "acked"
    old_acked = make(complete, acked, "20261109T100000Z.ndjson.gz", 8)
    old_unacked = make(complete, acked, "20261109T110000Z.ndjson.gz", 8, ack=False)
    young_acked = make(complete, acked, "20261109T120000Z.ndjson.gz", 1)

    deleted = cleanup(complete, acked, 7, NOW)

    assert deleted == [Path("TEST/2026/11/09/20261109T100000Z.ndjson.gz")]
    assert not old_acked.exists()
    assert not old_acked.with_name(old_acked.name + ".sha256").exists()
    assert not (acked / "TEST/2026/11/09/20261109T100000Z.ndjson.gz.ack").exists()
    assert old_unacked.exists()
    assert young_acked.exists()


def test_removes_orphan_acks_after_retention(tmp_path):
    complete, acked = tmp_path / "complete", tmp_path / "acked"
    complete.mkdir()
    orphan_old = acked / "TEST/2026/11/01/20261101T000000Z.ndjson.gz.ack"
    orphan_new = acked / "TEST/2026/11/19/20261119T000000Z.ndjson.gz.ack"
    for p, age in ((orphan_old, 8), (orphan_new, 1)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        os.utime(p, (NOW.timestamp() - age * DAY,) * 2)

    cleanup(complete, acked, 7, NOW)

    assert not orphan_old.exists()
    assert orphan_new.exists()


def test_free_space(tmp_path):
    free, ratio = free_space(tmp_path)
    assert free > 0
    assert 0 < ratio <= 1
