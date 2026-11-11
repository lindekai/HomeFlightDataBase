"""Die geplanten Flüge der readsb-Attrappe ergeben die im E2E-Test erwarteten Bewertungen."""

from datetime import UTC, datetime, timedelta

import pytest
from synthetic import serve
from synthetic.routes import LOCAL, PROCEDURES_FILE

from analysis.assign import Reference, assign
from analysis.deviation import corridor, samples, section
from analysis.direction import flight_heading, vote
from analysis.procedures import read_procedures
from analysis.role import determine_role
from analysis.segment import Point

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
RADIUS_M = 25000.0  # wie ANALYSIS_BER_RADIUS_M in tests/e2e/compose.yml


def flight(hex_: str, start_s: int, end_s: int) -> list[Point]:
    out = []
    for s in range(start_s, end_s):
        for p in serve.scripted(float(s)):
            if p["hex"] == hex_:
                ts = T0 + timedelta(seconds=s)
                out.append(
                    Point(ts, p["lat"], p["lon"], p["alt_baro"], p["baro_rate"], p["flight"], False)
                )
    return out


def references() -> list[Reference]:
    procs = read_procedures(PROCEDURES_FILE, ber_lat=50.0, ber_lon=10.0, ber_radius_m=RADIUS_M)
    return [
        Reference(
            i,
            p.name,
            p.kind,
            p.direction,
            p.sector,
            [LOCAL.xy(*c) for c in p.line],
            p.valid_from,
            p.valid_to,
        )
        for i, p in enumerate(procs)
    ]


@pytest.mark.parametrize(
    "hex_, window, role, procedure, deviation",
    [
        ("ff0110", (30, 330), "departure", "WNORD1W", False),
        ("ff0111", (60, 420), "arrival", "ONORD1W", False),
        ("ff0112", (150, 550), "departure", "WNORD1W", True),
    ],
)
def test_scripted_flight(hex_, window, role, procedure, deviation):
    points = flight(hex_, *window)
    r = determine_role(
        points, LOCAL, ber_radius_m=RADIUS_M, near_m=10000, max_alt_ft=3000, vrate_fpm=300
    )
    assert r.role == role
    assert vote(flight_heading(r, near_m=10000, dist_m=15000), [270.0, 90.0], tol_deg=30) == "west"
    track = samples(points, LOCAL)
    a = assign(role, "west", r.sector, track, references(), max_alt_ft=None, ratio=2.0)
    assert (a.reference.name, a.confidence) == (procedure, "high")
    c = corridor(section(track, a.reference.line, None), half_width_m=1852, min_s=30)
    assert c.deviation is deviation


def test_one_flight_per_cycle_and_detour_once():
    calls = {p["flight"] for s in range(0, 1300) for p in serve.scripted(float(s))}
    assert {"TST100", "TST101", "TST102", "TST110", "TST111", "TST120"} <= calls
    assert not any(c.startswith("TST12") and c != "TST120" for c in calls)
