import gzip
import os
from datetime import UTC, datetime
from pathlib import Path

from recorder.files import (
    file_stem,
    finalize,
    last_activity,
    period_start,
    recover,
    sha256_file,
    truncate_incomplete_line,
)


def test_file_stem_uses_utc_start():
    start = datetime(2026, 11, 9, 14, 5, 7, tzinfo=UTC)
    assert file_stem("TEST", start) == Path("TEST/2026/11/09/20261109T140507Z")


def test_period_start_aligns_to_rotation():
    ts = datetime(2026, 11, 9, 14, 59, 59, tzinfo=UTC)
    assert period_start(ts, 3600) == datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
    assert period_start(ts, 10) == datetime(2026, 11, 9, 14, 59, 50, tzinfo=UTC)


def test_finalize_compresses_and_writes_sidecar(tmp_path):
    cur, comp = tmp_path / "current", tmp_path / "complete"
    src = cur / "TEST/2026/11/09/20261109T140000Z.ndjson"
    src.parent.mkdir(parents=True)
    src.write_bytes(b'{"a":1}\n')

    target = finalize(src, cur, comp)

    assert target == comp / "TEST/2026/11/09/20261109T140000Z.ndjson.gz"
    assert gzip.decompress(target.read_bytes()) == b'{"a":1}\n'
    sidecar = target.with_name(target.name + ".sha256")
    assert sidecar.read_text() == f"{sha256_file(target)}  {target.name}\n"
    assert not src.exists()


def test_finalize_partial_marks_name(tmp_path):
    cur, comp = tmp_path / "current", tmp_path / "complete"
    src = cur / "TEST/2026/11/09/20261109T140000Z.ndjson"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"{}\n")
    target = finalize(src, cur, comp, partial=True)
    assert target.name == "20261109T140000Z.partial.ndjson.gz"


def test_truncate_incomplete_line(tmp_path):
    p = tmp_path / "f.ndjson"
    p.write_bytes(b'{"a":1}\n{"b":')
    truncate_incomplete_line(p)
    assert p.read_bytes() == b'{"a":1}\n'


def test_truncate_keeps_complete_file_and_empties_single_fragment(tmp_path):
    ok, frag = tmp_path / "ok.ndjson", tmp_path / "frag.ndjson"
    ok.write_bytes(b'{"a":1}\n')
    frag.write_bytes(b'{"a":')
    truncate_incomplete_line(ok)
    truncate_incomplete_line(frag)
    assert ok.read_bytes() == b'{"a":1}\n'
    assert frag.read_bytes() == b""


def test_recover_finalizes_as_partial_and_drops_empty(tmp_path):
    cur, comp = tmp_path / "current", tmp_path / "complete"
    day = cur / "TEST/2026/11/09"
    day.mkdir(parents=True)
    (day / "20261109T140000Z.ndjson").write_bytes(b'{"a":1}\n{"b"')
    (day / "20261109T150000Z.ndjson").write_bytes(b'{"x"')

    recovered = recover(cur, comp)

    assert recovered == [comp / "TEST/2026/11/09/20261109T140000Z.partial.ndjson.gz"]
    assert gzip.decompress(recovered[0].read_bytes()) == b'{"a":1}\n'
    assert list(cur.rglob("*.ndjson")) == []


def test_last_activity_returns_newest_mtime(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "old").write_text("x")
    (b / "new").write_text("y")
    os.utime(a / "old", (1_700_000_000, 1_700_000_000))
    os.utime(b / "new", (1_800_000_000, 1_800_000_000))
    assert last_activity(a, b) == datetime.fromtimestamp(1_800_000_000, tz=UTC)
    assert last_activity(tmp_path / "missing") is None
