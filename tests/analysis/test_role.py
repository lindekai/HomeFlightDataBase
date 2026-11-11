from datetime import UTC, datetime, timedelta

import pytest
from synthetic.routes import (
    LOCAL,
    ONMID,
    ONORD,
    TEAST,
    THR_09,
    THR_27,
    TWEST,
    WNMID,
    WNORD,
    fly,
    points,
)

from analysis.role import determine_role

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
LIMITS = {"ber_radius_m": 40000.0, "near_m": 10000.0, "max_alt_ft": 3000, "vrate_fpm": 300.0}


def role_of(rows):
    return determine_role(points(rows), LOCAL, **LIMITS)


def test_departure():
    r = role_of(fly([THR_09, TWEST, WNMID, WNORD], T0))
    assert (r.role, r.ref_ts, r.sector) == ("departure", T0, "NW")
    assert r.outward[0] == (pytest.approx(-1500), pytest.approx(0, abs=1e-6))


def test_arrival():
    # 647 Positionen, letzte bei x = 1576 m in 233 ft
    rows = fly([ONORD, ONMID, TEAST, THR_27], T0, speed_kt=180, alt_ft=11000, vrate_fpm=-1000)
    r = role_of(rows)
    assert (r.role, r.ref_ts, r.sector) == ("arrival", T0 + timedelta(seconds=646), "NO")
    assert r.outward[0] == (pytest.approx(1576.48, abs=0.01), pytest.approx(0, abs=1e-6))


def test_level_overflight_has_no_role():
    assert role_of(fly([(-30000, 2000), (30000, 2000)], T0, alt_ft=2000, vrate_fpm=0)) is None


def test_departure_must_start_near_and_low():
    assert role_of(fly([(-12000, 0), (-40000, 0)], T0)) is None  # beginnt 12 km entfernt
    assert role_of(fly([THR_09, (-40000, 0)], T0, alt_ft=3500)) is None


def test_weak_climb_is_no_departure():
    assert role_of(fly([THR_09, (-40000, 0)], T0, vrate_fpm=200)) is None


def test_flight_outside_radius_has_no_role():
    assert role_of(fly([(-60000, 0), (-45000, 0)], T0)) is None
