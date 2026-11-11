"""Heuristische Einstufung eines Überflugs als Anflug, Abflug oder sonstiger Flug.

Grundlage sind nur Höhenverlauf und Abstandsänderung zum Flughafen-Referenzpunkt. Die
Einstufung ist keine Verfahrenszuordnung; diese folgt in Meilenstein 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from analysis.segment import Point, haversine_m


@dataclass(frozen=True)
class Classification:
    category: str
    basis: dict


def vertical_rate(points: list[Point]) -> tuple[float, str]:
    rates = [p.vrate_fpm for p in points if p.vrate_fpm is not None]
    if rates:
        return fmean(rates), "baro_rate"
    first, last = points[0], points[-1]
    dt = (last.ts - first.ts).total_seconds()
    return ((last.alt_ft - first.alt_ft) / dt * 60 if dt > 0 else 0.0), "altitude"


def classify(
    points: list[Point],
    *,
    ber_lat: float,
    ber_lon: float,
    min_positions: int,
    vrate_fpm: float,
    ber_radius_m: float,
) -> Classification:
    with_alt = [p for p in points if p.alt_ft is not None]
    basis: dict = {
        "n_positions": len(with_alt),
        "thresholds": {
            "min_positions": min_positions,
            "vrate_fpm": vrate_fpm,
            "ber_radius_m": ber_radius_m,
        },
    }
    if len(with_alt) < min_positions:
        return Classification("unknown", basis | {"reason": "zu wenige Positionen mit Höhe"})

    vr, source = vertical_rate(with_alt)
    d_first = haversine_m(with_alt[0].lat, with_alt[0].lon, ber_lat, ber_lon)
    d_last = haversine_m(with_alt[-1].lat, with_alt[-1].lon, ber_lat, ber_lon)
    change = d_last - d_first
    basis |= {
        "vrate_fpm": round(vr),
        "vrate_source": source,
        "ber_dist_m": round(min(d_first, d_last)),
        "ber_dist_change_m": round(change),
    }
    near = min(d_first, d_last) < ber_radius_m
    sinking, climbing = vr < -vrate_fpm, vr > vrate_fpm
    if near and ((sinking and change > 0) or (climbing and change < 0)):
        return Classification(
            "unknown", basis | {"reason": "Höhenverlauf widerspricht Abstandsänderung"}
        )
    if near and sinking and change < 0:
        return Classification("arrival", basis)
    if near and climbing and change > 0:
        return Classification("departure", basis)
    return Classification("overflight", basis)
