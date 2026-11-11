from datetime import UTC, datetime, timedelta

from analysis.segment import Point, haversine_m, segment

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
DEG_LON_M = 71_696.0  # Meter je Grad Länge bei 50° Breite


def pt(s, lat=50.0, east_m=None, alt=3000, cs="TEST01", ground=False):
    lon = 10.0 + (100.0 * s if east_m is None else east_m) / DEG_LON_M
    return Point(T0 + timedelta(seconds=s), lat, lon, alt, 0, cs, ground)


def run(points):
    return segment("ff0001", points, gap_s=600, max_speed_kt=800)


def test_continuous_track_is_one_flight():
    (seg,) = run([pt(s) for s in range(10)])
    assert len(seg.points) == 10 and seg.n_outliers == 0
    assert (seg.first_ts, seg.last_ts) == (T0, T0 + timedelta(seconds=9))


def test_pause_longer_than_gap_splits():
    segs = run([pt(s) for s in range(5)] + [pt(s) for s in range(700, 705)])
    assert [len(s.points) for s in segs] == [5, 5]


def test_callsign_change_splits_but_missing_callsign_does_not():
    points = [pt(s, cs="AAA1") for s in range(3)] + [pt(3, cs=None)]
    points += [pt(s, cs="BBB2") for s in range(4, 8)]
    segs = run(points)
    assert [s.callsign for s in segs] == ["AAA1", "BBB2"]
    assert [len(s.points) for s in segs] == [4, 4]


def test_landing_splits_and_ground_positions_are_dropped():
    points = [pt(s) for s in range(5)] + [pt(s, ground=True) for s in range(5, 10)]
    points += [pt(s) for s in range(10, 15)]
    segs = run(points)
    assert [len(s.points) for s in segs] == [5, 5]
    assert not any(p.on_ground for s in segs for p in s.points)


def test_implausible_jump_is_dropped_as_outlier():
    points = [pt(s) for s in range(10)]
    points[5] = pt(5, lat=51.0)
    (seg,) = run(points)
    assert len(seg.points) == 9 and seg.n_outliers == 1


def test_outlier_as_first_point_is_replaced():
    points = [pt(0, lat=51.0)] + [pt(s) for s in range(1, 10)]
    (seg,) = run(points)
    assert len(seg.points) == 9 and seg.n_outliers == 1
    assert seg.points[0].lat == 50.0


def test_single_positions_are_not_flights():
    assert run([pt(0), pt(1000)]) == []


def test_duplicate_timestamps_are_ignored():
    (seg,) = run([pt(0), pt(0), pt(1)])
    assert len(seg.points) == 2


def test_callsign_is_most_common():
    points = [pt(0, cs=None), pt(1, cs="Y2"), pt(2, cs=None), pt(3, cs="Y2")]
    (seg,) = run(points)
    assert seg.callsign == "Y2"


def test_haversine_one_degree_latitude():
    assert abs(haversine_m(50.0, 10.0, 51.0, 10.0) - 111_195) < 50
