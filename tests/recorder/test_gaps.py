from datetime import UTC, datetime, timedelta

from recorder.gaps import GapDetector

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)


def at(s):
    return T0 + timedelta(seconds=s)


def test_no_gap_while_fresh():
    g = GapDetector(5)
    assert g.observe(at(0), at(0)) is None
    assert g.observe(at(1), at(1)) is None
    assert not g.in_gap


def test_gap_from_last_good_until_recovery():
    g = GapDetector(5)
    g.observe(at(0), at(0))
    assert g.observe(at(1), None) is None
    assert g.in_gap
    assert g.observe(at(2), None) is None
    gap = g.observe(at(3), at(3))
    assert gap == {
        "from": "2026-11-09T14:00:00.000Z",
        "to": "2026-11-09T14:00:03.000Z",
        "reason": "no_data",
    }
    assert not g.in_gap


def test_stale_data_counts_as_gap():
    g = GapDetector(5)
    g.observe(at(0), at(0))
    assert g.observe(at(10), at(4)) is None
    assert g.observe(at(11), at(11))["reason"] == "stale_data"


def test_flush_closes_open_gap():
    g = GapDetector(5)
    g.observe(at(0), at(0))
    g.observe(at(1), None)
    assert g.flush(at(7))["to"] == "2026-11-09T14:00:07.000Z"
    assert g.flush(at(8)) is None
