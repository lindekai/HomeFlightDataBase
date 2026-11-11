import math

import pytest

from analysis.geo import Local, angle_diff, azimuth_deg, exit_point, length, project
from analysis.segment import haversine_m

LOCAL = Local(50.0, 10.0)


def test_round_trip_and_true_distance_from_center():
    lat, lon = LOCAL.latlon(12000.0, -8000.0)
    x, y = LOCAL.xy(lat, lon)
    assert (x, y) == (pytest.approx(12000.0, abs=1e-6), pytest.approx(-8000.0, abs=1e-6))
    assert math.hypot(x, y) == pytest.approx(haversine_m(50.0, 10.0, lat, lon), rel=1e-9)
    assert LOCAL.xy(50.0, 10.0) == (0.0, 0.0)


def test_azimuth_and_angle_diff():
    assert azimuth_deg((0, 0), (0, 1)) == 0
    assert azimuth_deg((0, 0), (1, 0)) == 90
    assert azimuth_deg((0, 0), (0, -1)) == 180
    assert azimuth_deg((0, 0), (-1, 0)) == 270
    assert angle_diff(350, 10) == 20
    assert angle_diff(90, 270) == 180


def test_exit_point():
    assert exit_point([(0, 0), (0, 20000)], 15000) == (0, 15000)
    assert exit_point([(0, 0), (0, 5000)], 15000) is None
    assert exit_point([(0, 20000), (0, 30000)], 15000) == (0, 20000)
    x, y = exit_point([(0, 0), (30000, 30000)], 15000)
    assert (x, y) == (pytest.approx(15000 / math.sqrt(2)), pytest.approx(15000 / math.sqrt(2)))


def test_project_inside_and_beyond_line():
    line = [(0.0, 0.0), (10000.0, 0.0)]
    p = project((5000, 300), line)
    assert (p.along_m, p.dist_m, p.within) == (5000, 300, True)
    before = project((-200, 100), line)
    assert (before.dist_m, before.within) == (pytest.approx(223.607, abs=1e-3), False)
    assert project((10500, 0), line).within is False


def test_project_at_inner_vertex_counts_as_within():
    line = [(0.0, 0.0), (10000.0, 0.0), (10000.0, 10000.0)]
    p = project((10500, -500), line)
    assert (p.along_m, p.dist_m, p.within) == (10000, pytest.approx(707.107, abs=1e-3), True)


def test_length():
    assert length([(0, 0), (3000, 4000), (3000, 0)]) == 9000
