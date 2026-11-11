from datetime import UTC, datetime, timedelta

from analysis.config import Config
from analysis.events import Crossing, build_event, interp_alt, sector
from analysis.segment import Point

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
CFG = Config(db_dsn="unused", ber_lat=49.0, ber_lon=8.0)


def t(s):
    return T0 + timedelta(seconds=s)


def pts(alts, step=10):
    return [
        Point(t(i * step), 50.0, 10.0 + i / 1000, a, 0, "TEST01", False) for i, a in enumerate(alts)
    ]


def test_sector():
    assert [sector(h) for h in (0, 22.4, 22.6, 90, 180, 270, 337.6, None)] == [
        "N",
        "N",
        "NO",
        "O",
        "S",
        "W",
        "N",
        None,
    ]


def test_interp_alt():
    points = pts([3000, 2000, None, 1000])
    assert interp_alt(points, t(5)) == 2500
    assert interp_alt(points, t(25)) == 1250  # überspringt Position ohne Höhe
    assert interp_alt(points, t(-5)) == 3000  # vor Beginn: erster Wert
    assert interp_alt(pts([None, None]), t(5)) is None


def test_build_event_values():
    points = pts([3000, 2500, 2000, 2500, 3000, 3000, 3000, 3000])
    c = Crossing(7, t(5), t(35), t(20), 1234.5, 90.0)
    ev = build_event(c, points, relevance_ft=2200, cfg=CFG)
    assert ev["geofence_id"] == 7
    assert ev["duration_s"] == 30
    assert ev["min_alt_ft"] == 2000 and ev["alt_at_closest_ft"] == 2000
    assert ev["relevant"] is True
    assert ev["n_positions_inside"] == 3
    assert ev["max_position_gap_s"] == 10
    assert ev["heading_sector"] == "O"
    assert ev["category"] in ("overflight", "unknown")
    assert "thresholds" in ev["category_basis"]


def test_not_relevant_above_limit():
    ev = build_event(Crossing(1, t(5), t(35), t(20), 0, 90.0), pts([9000] * 8), 2200, CFG)
    assert ev["relevant"] is False


def test_zone_between_positions_uses_interpolation():
    points = pts([3000, 2000], step=60)
    ev = build_event(Crossing(1, t(20), t(40), t(30), 10, 0.0), points, 10000, CFG)
    assert ev["n_positions_inside"] == 0
    assert ev["min_alt_ft"] == 2333  # Austritt bei 40 s: 3000 - 1000 * 40/60
    assert ev["max_position_gap_s"] == 60
