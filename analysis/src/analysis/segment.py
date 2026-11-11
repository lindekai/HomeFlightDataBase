"""Zerlegt die Positionen eines Flugzeugs in zusammenhängende Flüge (ohne Datenbank)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

EARTH_RADIUS_M = 6_371_008.8
KT_TO_MS = 1852 / 3600


@dataclass(frozen=True)
class Point:
    ts: datetime
    lat: float
    lon: float
    alt_ft: int | None
    vrate_fpm: int | None
    callsign: str | None
    on_ground: bool


@dataclass
class Segment:
    icao24: str
    points: list[Point] = field(default_factory=list)
    n_outliers: int = 0

    @property
    def first_ts(self) -> datetime:
        return self.points[0].ts

    @property
    def last_ts(self) -> datetime:
        return self.points[-1].ts

    @property
    def callsign(self) -> str | None:
        names = [p.callsign for p in self.points if p.callsign]
        return Counter(names).most_common(1)[0][0] if names else None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def segment(
    icao24: str, points: Iterable[Point], *, gap_s: float, max_speed_kt: float
) -> list[Segment]:
    """Zeitlich sortierte Positionen → Flüge mit mindestens zwei gültigen Positionen.

    Neuer Flug nach einer Pause > ``gap_s``, bei Wechsel des Rufzeichens oder nach einer
    Landung. Positionen am Boden gehören nicht zur Spur. Positionen, die nur mit mehr als
    ``max_speed_kt`` erreichbar wären, werden als Ausreißer verworfen und gezählt.
    """
    max_speed = max_speed_kt * KT_TO_MS
    segments: list[Segment] = []
    cur: Segment | None = None
    callsign: str | None = None
    landed = False
    for p in points:
        if p.on_ground:
            landed = True
            continue
        last = cur.points[-1] if cur else None
        if (
            cur is None
            or landed
            or (p.ts - last.ts).total_seconds() > gap_s
            or (p.callsign and callsign and p.callsign != callsign)
        ):
            cur = Segment(icao24, [p])
            segments.append(cur)
            callsign, landed = p.callsign, False
            continue
        dt = (p.ts - last.ts).total_seconds()
        if dt <= 0:
            continue
        if haversine_m(last.lat, last.lon, p.lat, p.lon) / dt > max_speed:
            cur.n_outliers += 1
            if len(cur.points) == 1:
                # Ein einzelner Startpunkt kann selbst der Ausreißer sein.
                cur.points[0] = p
                callsign = p.callsign or callsign
            continue
        cur.points.append(p)
        callsign = p.callsign or callsign
    return [s for s in segments if len(s.points) >= 2]
