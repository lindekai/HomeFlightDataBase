import gzip
import json
import os
from datetime import UTC, datetime, timedelta

from recorder.config import Config
from recorder.main import Recorder
from synthetic.generator import aircraft, snapshot

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


def make_cfg(tmp_path):
    return Config(receiver_id="TEST", readsb_url="http://unused", data_dir=tmp_path, synthetic=True)


def read_all(complete_dir):
    lines = []
    for gz in sorted(complete_dir.rglob("*.ndjson.gz")):
        lines += [json.loads(line) for line in gzip.open(gz, "rt").read().splitlines()]
    return lines


def test_snapshots_gap_and_housekeeping(tmp_path):
    clock = FakeClock(T0)
    available = iter([True, True, False, False, True])

    def fetch():
        if next(available):
            return snapshot(clock().timestamp(), [aircraft()])
        return None

    rec = Recorder(make_cfg(tmp_path), fetch=fetch, now_fn=clock, clock_fn=lambda: 0.02)
    rec.start()
    for _ in range(5):
        rec.tick()
        clock.advance(1)
    rec.stop()

    lines = read_all(rec.complete_dir)
    assert [line["type"] for line in lines] == [
        "snapshot",
        "clock",
        "status",
        "snapshot",
        "gap",
        "snapshot",
    ]
    gap = lines[4]
    assert (gap["from"], gap["to"], gap["reason"]) == (
        "2026-11-09T14:00:01.000Z",
        "2026-11-09T14:00:04.000Z",
        "no_data",
    )
    assert all(line["synthetic"] is True and line["receiver_id"] == "TEST" for line in lines)
    assert lines[1]["offset_s"] == 0.02
    assert list(rec.complete_dir.rglob("*.partial.ndjson.gz"))


def test_unchanged_readsb_timestamp_is_not_written_twice(tmp_path):
    clock = FakeClock(T0)
    frozen = snapshot(T0.timestamp(), [aircraft()])
    rec = Recorder(make_cfg(tmp_path), fetch=lambda: frozen, now_fn=clock, clock_fn=lambda: 0)
    rec.start()
    rec.tick()
    clock.advance(1)
    rec.tick()
    rec.stop()
    types = [line["type"] for line in read_all(rec.complete_dir)]
    assert types.count("snapshot") == 1


def test_restart_recovers_file_and_logs_gap(tmp_path):
    stale = tmp_path / "current/TEST/2026/11/09/20261109T130000Z.ndjson"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b'{"type":"snapshot"}\n{"type":')
    last = (T0 - timedelta(minutes=10)).timestamp()
    os.utime(stale, (last, last))

    clock = FakeClock(T0)
    rec = Recorder(make_cfg(tmp_path), fetch=lambda: None, now_fn=clock, clock_fn=lambda: None)
    rec.start()
    rec.stop()

    recovered = rec.complete_dir / "TEST/2026/11/09/20261109T130000Z.partial.ndjson.gz"
    assert gzip.decompress(recovered.read_bytes()) == b'{"type":"snapshot"}\n'
    gaps = [line for line in read_all(rec.complete_dir) if line["type"] == "gap"]
    assert gaps[0]["reason"] == "recorder_restart"
    assert gaps[0]["from"] == "2026-11-09T13:50:00.000Z"


def test_heartbeat_only_with_fresh_data(tmp_path):
    clock = FakeClock(T0)
    rec = Recorder(make_cfg(tmp_path), fetch=lambda: None, now_fn=clock, clock_fn=lambda: 0)
    rec.start()
    rec.tick()
    assert not rec.heartbeat.exists()
    rec._fetch = lambda: snapshot(clock().timestamp(), [])
    clock.advance(1)
    rec.tick()
    assert rec.heartbeat.exists()
    rec.stop()
