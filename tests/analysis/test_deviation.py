from datetime import UTC, datetime, timedelta

import pytest

from analysis.deviation import Sample, approach, corridor, review, section

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
LINE = [(0.0, 0.0), (20000.0, 0.0)]
W = {"half_width_m": 1852.0, "min_s": 30.0}


def track(offset, n=140, x0=1000.0, alt=lambda t: 3000):
    """Je Sekunde 100 m nach Osten, seitlicher Versatz ``offset(t)``."""
    return [
        Sample(T0 + timedelta(seconds=t), (x0 + 100.0 * t, offset(t)), alt(t)) for t in range(n)
    ]


def test_long_excursion_is_deviation():
    # 2500 m Versatz von t=50 bis t=89; Austritt bei 49 + 1852/2500, Rückkehr bei 89 + 648/2500
    c = corridor(section(track(lambda t: 2500.0 if 50 <= t < 90 else 0.0), LINE, None), **W)
    assert c.deviation is True
    assert c.outside_s == pytest.approx(39.5184)
    assert c.outside_m == pytest.approx(5197.04, abs=0.01)
    assert (c.max_dev_m, c.max_position_gap_s) == (2500.0, 1.0)
    assert (c.eval_from, c.eval_to) == (T0, T0 + timedelta(seconds=139))


def test_short_overshoot_is_no_deviation():
    c = corridor(section(track(lambda t: 2500.0 if 50 <= t < 70 else 0.0), LINE, None), **W)
    assert c.deviation is False
    assert c.outside_s == pytest.approx(19.5184)


def test_section_starting_outside():
    c = corridor(section(track(lambda t: 2500.0 if t < 40 else 0.0), LINE, None), **W)
    assert c.deviation is True
    assert c.outside_s == pytest.approx(39.2592)
    assert c.outside_m == pytest.approx(4548.52, abs=0.01)


def test_section_is_limited_to_line_extent():
    sec = section(track(lambda t: 0.0, n=300, x0=-5000.0), LINE, None)
    assert len(sec) == 201  # x = 0 … 20000 m
    assert (sec[0][0].xy, sec[-1][0].xy) == ((0.0, 0.0), (20000.0, 0.0))


def test_section_altitude_limit():
    sec = section(track(lambda t: 0.0, alt=lambda t: 2000 + 20 * t), LINE, 3000)
    assert len(sec) == 51 and sec[-1][0].alt_ft == 3000
    no_alt = section(track(lambda t: 0.0, alt=lambda t: None), LINE, 3000)
    assert no_alt == []


def test_approach_picks_zone_with_smallest_difference():
    flight = [(float(x), -2500.0 if 9000 <= x <= 11000 else 0.0) for x in range(0, 20001, 100)]
    zones = [(1, (10000.0, 8000.0)), (2, (10000.0, -3000.0))]
    a = approach(flight, LINE, zones, tol_m=1852)
    assert (a.geofence_id, a.min_dist_ref_m, a.proc_dist_ref_m, a.approach) == (2, 500, 3000, True)


def test_no_approach_on_the_line():
    flight = [(float(x), 0.0) for x in range(0, 20001, 100)]
    a = approach(flight, LINE, [(2, (10000.0, -3000.0))], tol_m=1852)
    assert (a.min_dist_ref_m, a.approach) == (3000, False)
    assert approach(flight, LINE, [], tol_m=1852).geofence_id is None


GOOD = {
    "deviation": True,
    "approach": False,
    "confidence": "high",
    "in_reception_gap": False,
    "max_position_gap_s": 5.0,
    "max_gap_s": 30.0,
    "relevant_event": True,
}


def test_review_when_all_conditions_hold():
    assert review(**GOOD) == (
        True,
        ["Abweichung", "Sicherheit hoch", "Datenqualität ausreichend", "relevanter Überflug"],
    )


@pytest.mark.parametrize(
    "change",
    [
        {"deviation": False},
        {"confidence": "low"},
        {"in_reception_gap": True},
        {"in_reception_gap": None},
        {"max_position_gap_s": 31.0},
        {"relevant_event": False},
    ],
)
def test_no_review_if_one_condition_fails(change):
    flagged, _ = review(**(GOOD | change))
    assert flagged is False


def test_review_by_approach_with_medium_confidence():
    flagged, reasons = review(
        **(GOOD | {"deviation": False, "approach": True, "confidence": "medium"})
    )
    assert flagged is True and reasons[:2] == ["Annäherung", "Sicherheit mittel"]
