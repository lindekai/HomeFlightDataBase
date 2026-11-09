import gzip
import json
from datetime import UTC, datetime

from recorder.files import sha256_file
from recorder.writer import RotatingWriter


def ts(h, m, s):
    return datetime(2026, 11, 9, h, m, s, tzinfo=UTC)


def read_gz(path):
    return [json.loads(line) for line in gzip.open(path, "rt").read().splitlines()]


def test_rotation_finalizes_previous_period(tmp_path):
    cur, comp = tmp_path / "current", tmp_path / "complete"
    w = RotatingWriter("TEST", cur, comp, 3600)

    assert w.write({"n": 1}, ts(14, 59, 59)) is None
    done = w.write({"n": 2}, ts(15, 0, 0))

    assert done == comp / "TEST/2026/11/09/20261109T145959Z.ndjson.gz"
    assert read_gz(done) == [{"n": 1}]
    assert done.with_name(done.name + ".sha256").read_text().startswith(sha256_file(done))
    assert list(cur.rglob("*.ndjson")) == [cur / "TEST/2026/11/09/20261109T150000Z.ndjson"]


def test_rotate_if_due_without_write(tmp_path):
    w = RotatingWriter("TEST", tmp_path / "c", tmp_path / "d", 10)
    w.write({"n": 1}, ts(14, 0, 1))
    assert w.rotate_if_due(ts(14, 0, 9)) is None
    assert w.rotate_if_due(ts(14, 0, 10)) is not None


def test_close_partial(tmp_path):
    w = RotatingWriter("TEST", tmp_path / "c", tmp_path / "d", 3600)
    w.write({"n": 1}, ts(14, 10, 0))
    done = w.close(partial=True)
    assert done.name == "20261109T141000Z.partial.ndjson.gz"
    assert w.close() is None
