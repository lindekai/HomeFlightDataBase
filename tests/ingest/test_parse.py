from datetime import UTC, datetime

import pytest
from synthetic.generator import aircraft, snapshot
from synthetic.rawfiles import line, write_raw_file

from ingest.parse import InconsistentFile, parse_file

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
NOW = T0.timestamp()


def gap_line(reason="no_data"):
    span = {"from": "2026-11-09T13:59:00.000Z", "to": "2026-11-09T13:59:30.000Z"}
    return line("gap", T0, **span, reason=reason)


def test_position_time_from_seen_pos(tmp_path):
    path = write_raw_file(tmp_path, T0, [snapshot(NOW + 10.0, [aircraft(seen_pos=2.3)])])
    parsed = parse_file(path)
    (pos,) = parsed.positions
    assert pos.ts == datetime(2026, 11, 9, 14, 0, 7, 700000, tzinfo=UTC)
    assert (pos.icao24, pos.callsign, pos.lat, pos.lon) == ("ff0001", "TEST01", 50.0, 10.0)
    assert (pos.alt_baro_ft, pos.alt_geom_ft, pos.source_type, pos.rssi_dbfs) == (
        3000,
        3100,
        "adsb_icao",
        -20.5,
    )
    assert parsed.receiver_id == "TEST"
    assert parsed.synthetic is True


def test_ground_and_missing_position(tmp_path):
    planes = [aircraft(hex="ff0002", alt_baro="ground"), aircraft(hex="ff0003", seen_pos=None)]
    parsed = parse_file(write_raw_file(tmp_path, T0, [snapshot(NOW, planes)]))
    (pos,) = parsed.positions
    assert pos.icao24 == "ff0002"
    assert pos.on_ground is True
    assert pos.alt_baro_ft is None


def test_same_position_in_consecutive_snapshots_is_deduplicated(tmp_path):
    snaps = [
        snapshot(NOW, [aircraft(seen_pos=0.5)]),
        snapshot(NOW + 1.0, [aircraft(seen_pos=1.5)]),  # dieselbe Position, 1 s älter
        snapshot(NOW + 2.0, [aircraft(seen_pos=0.2)]),  # neue Position
    ]
    parsed = parse_file(write_raw_file(tmp_path, T0, snaps))
    assert len(parsed.positions) == 2
    seen = parsed.aircraft["ff0001"]
    assert (seen.registration, seen.type_code) == ("TEST-REG", "TST1")
    assert seen.first_seen < seen.last_seen


def test_gap_clock_status_and_period(tmp_path):
    extra = [
        gap_line(),
        line("clock", T0, offset_s=-0.4),
        line("clock", T0, offset_s=0.1),
        line("clock", T0, offset_s=None),
        line("status", T0, free_bytes=12345, free_ratio=0.5),
    ]
    parsed = parse_file(write_raw_file(tmp_path, T0, [snapshot(NOW, [])] * 3, extra=extra))
    (gap,) = parsed.gaps
    assert (gap.start.second, gap.end.second, gap.reason) == (0, 30, "no_data")
    assert parsed.clock_offset_max_s == 0.4
    assert parsed.receiver_free_bytes == 12345
    assert parsed.period_start == T0
    assert parsed.period_end == datetime(2026, 11, 9, 14, 0, 2, tzinfo=UTC)


def test_mixed_receiver_ids_raise(tmp_path):
    extra = [line("status", T0, receiver_id="OTHER", free_bytes=1)]
    path = write_raw_file(tmp_path, T0, [snapshot(NOW, [])], extra=extra)
    with pytest.raises(InconsistentFile):
        parse_file(path)


def test_malformed_lines_are_counted(tmp_path):
    extra = [{"type": "snapshot"}, ["kein", "objekt"]]
    parsed = parse_file(write_raw_file(tmp_path, T0, [snapshot(NOW, [])], extra=extra))
    assert parsed.bad_lines == 2
