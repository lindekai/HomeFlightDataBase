from datetime import UTC, datetime

import pytest

from analysis.direction import decide, flight_heading, vote, window_start
from analysis.role import Role

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
NEAR = {"near_m": 10000.0, "dist_m": 15000.0}


def test_window_start():
    assert window_start(datetime(2026, 11, 9, 14, 29, 59, tzinfo=UTC)) == T0
    assert window_start(datetime(2026, 11, 9, 14, 30, tzinfo=UTC)) == T0.replace(minute=30)


def test_heading_of_departure_and_arrival():
    west = [(-1500.0, 0.0), (-20000.0, 0.0)]
    dep = Role("departure", T0, west, "W")
    arr = Role("arrival", T0, west, "W")  # rückwärts: Anflug von Westen nach Osten
    assert flight_heading(dep, **NEAR) == pytest.approx(270.0)
    assert flight_heading(arr, **NEAR) == pytest.approx(90.0)


def test_heading_needs_direction_distance():
    short = Role("departure", T0, [(-1500.0, 0.0), (-14000.0, 0.0)], "W")
    assert flight_heading(short, **NEAR) is None


@pytest.mark.parametrize(
    "heading, expected", [(265, "west"), (300, "west"), (301, None), (80, "east"), (None, None)]
)
def test_vote(heading, expected):
    assert vote(heading, [270.0, 90.0], tol_deg=30) == expected


def test_vote_without_runways():
    assert vote(270, [], tol_deg=30) is None


@pytest.mark.parametrize(
    "votes, direction, share",
    [
        (["west"] * 5, "west", 1.0),  # klare Mehrheit
        (["west"] * 4 + ["east"], "west", 0.8),  # knapp
        (["west"] * 3 + ["east"], "unknown", 0.75),  # zu knapp
        (["east"] * 2, "unknown", 1.0),  # zu wenige Flüge
        ([], "unknown", None),
    ],
)
def test_decide(votes, direction, share):
    d = decide(votes, min_flights=3, min_share=0.8)
    assert (d.direction, d.n_flights, d.share) == (direction, len(votes), share)
    assert d.basis.startswith(f"{len(votes)} Stimmen")
