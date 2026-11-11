"""Rolle eines Flugs bezogen auf BER: Abflug, Anflug oder keine (ohne Datenbank)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from analysis.classify import vertical_rate
from analysis.events import sector
from analysis.geo import XY, Local, azimuth_deg, exit_point
from analysis.segment import Point


@dataclass(frozen=True)
class Role:
    role: str  # departure | arrival
    ref_ts: datetime  # Startzeit bzw. Landezeit: erste bzw. letzte Position des Teils
    outward: list[XY]  # Spur vom Flughafen weg: Abflug ab Teilbeginn, Anflug rückwärts
    sector: str  # Sektor beim Verlassen bzw. Betreten des BER-Radius


def determine_role(
    points: list[Point],
    local: Local,
    *,
    ber_radius_m: float,
    near_m: float,
    max_alt_ft: float,
    vrate_fpm: float,
) -> Role | None:
    """Betrachtet den Teil der Spur innerhalb ``ber_radius_m`` (erste bis letzte Position
    darin). Abflug: Teil beginnt näher als ``near_m`` unterhalb ``max_alt_ft`` und steigt im
    Mittel stärker als ``vrate_fpm``. Anflug spiegelbildlich am Ende des Teils mit Sinken."""
    xy = [local.xy(p.lat, p.lon) for p in points]
    inside = [i for i, q in enumerate(xy) if math.hypot(*q) < ber_radius_m]
    if not inside:
        return None
    i0, i1 = inside[0], inside[-1]
    part = [p for p in points[i0 : i1 + 1] if p.alt_ft is not None]
    if len(part) < 2:
        return None
    rate, _ = vertical_rate(part)

    def low_and_near(i: int) -> bool:
        p = points[i]
        return p.alt_ft is not None and p.alt_ft < max_alt_ft and math.hypot(*xy[i]) < near_m

    if rate > vrate_fpm and low_and_near(i0):
        role, ref_ts, outward = "departure", points[i0].ts, xy[i0:]
    elif rate < -vrate_fpm and low_and_near(i1):
        role, ref_ts, outward = "arrival", points[i1].ts, xy[: i1 + 1][::-1]
    else:
        return None
    edge = exit_point(outward, ber_radius_m) or outward[-1]
    return Role(role, ref_ts, outward, sector(azimuth_deg((0.0, 0.0), edge)))
