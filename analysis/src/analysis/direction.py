"""Betriebsrichtung: Stimme je Flug und Mehrheit je 30-Minuten-Fenster (ohne Datenbank)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from analysis.geo import angle_diff, azimuth_deg, exit_point
from analysis.procedures import direction_class
from analysis.role import Role

WINDOW = timedelta(minutes=30)


def window_start(ts: datetime) -> datetime:
    """Beginn des 30-Minuten-Fensters (UTC, auf :00 bzw. :30 ausgerichtet)."""
    epoch = int(ts.timestamp()) // 1800 * 1800
    return datetime.fromtimestamp(epoch, UTC)


def flight_heading(role: Role, *, near_m: float, dist_m: float) -> float | None:
    """Bezugskurs: zwischen den Spurpunkten am Rand von ``near_m`` und bei ``dist_m``,
    in Flugrichtung. ``None``, wenn die Spur ``dist_m`` nicht erreicht."""
    a = exit_point(role.outward, near_m)
    b = exit_point(role.outward, dist_m)
    if a is None or b is None or a == b:
        return None
    return azimuth_deg(a, b) if role.role == "departure" else azimuth_deg(b, a)


def vote(heading: float | None, runway_headings: list[float], *, tol_deg: float) -> str | None:
    """Stimme ``west``/``east`` nach dem nächstgelegenen Startbahnkurs, wenn der Flugkurs
    höchstens ``tol_deg`` davon abweicht; sonst keine Stimme."""
    if heading is None or not runway_headings:
        return None
    nearest = min(runway_headings, key=lambda r: angle_diff(heading, r))
    if angle_diff(heading, nearest) > tol_deg:
        return None
    return direction_class(nearest)


@dataclass(frozen=True)
class WindowDirection:
    direction: str  # west | east | unknown
    n_flights: int  # Stimmen im Fenster
    share: float | None  # Anteil der Mehrheit
    basis: str


def decide(votes: list[str], *, min_flights: int, min_share: float) -> WindowDirection:
    counts = Counter(votes)
    n = len(votes)
    basis = f"{n} Stimmen: {counts['west']} west, {counts['east']} east"
    if n == 0:
        return WindowDirection("unknown", 0, None, basis)
    leader, top = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    share = top / n
    if n >= min_flights and share >= min_share:
        return WindowDirection(leader, n, share, basis)
    return WindowDirection("unknown", n, share, basis)
