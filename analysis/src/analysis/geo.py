"""Lokale Ebene um den Flughafen-Referenzpunkt und Linienrechnung (ohne Datenbank).

Mittabstandstreue Azimutalprojektion auf der Kugel: Abstände und Richtungen vom Mittelpunkt
sind exakt, übrige Abstände im Umkreis von 100 km auf wenige Meter genau – vernachlässigbar
gegenüber der Korridorbreite. Koordinaten in der Ebene: x nach Osten, y nach Norden, in m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from analysis.segment import EARTH_RADIUS_M

XY = tuple[float, float]


class Local:
    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0, self.lon0 = lat0, lon0
        self._sin0 = math.sin(math.radians(lat0))
        self._cos0 = math.cos(math.radians(lat0))

    def xy(self, lat: float, lon: float) -> XY:
        phi, dl = math.radians(lat), math.radians(lon - self.lon0)
        cos_c = self._sin0 * math.sin(phi) + self._cos0 * math.cos(phi) * math.cos(dl)
        c = math.acos(max(-1.0, min(1.0, cos_c)))
        k = 1.0 if c < 1e-12 else c / math.sin(c)
        x = k * math.cos(phi) * math.sin(dl)
        y = k * (self._cos0 * math.sin(phi) - self._sin0 * math.cos(phi) * math.cos(dl))
        return x * EARTH_RADIUS_M, y * EARTH_RADIUS_M

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        rho = math.hypot(x, y)
        if rho < 1e-9:
            return self.lat0, self.lon0
        c = rho / EARTH_RADIUS_M
        lat = math.asin(math.cos(c) * self._sin0 + y * math.sin(c) * self._cos0 / rho)
        lon = math.radians(self.lon0) + math.atan2(
            x * math.sin(c), rho * self._cos0 * math.cos(c) - y * self._sin0 * math.sin(c)
        )
        return math.degrees(lat), (math.degrees(lon) + 540) % 360 - 180


def azimuth_deg(a: XY, b: XY) -> float:
    """Kurs von ``a`` nach ``b`` in Grad (0 = Nord, 90 = Ost)."""
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def angle_diff(a: float, b: float) -> float:
    """Kleinster Winkel zwischen zwei Kursen in Grad (0–180)."""
    return abs((a - b + 180) % 360 - 180)


def length(line: list[XY]) -> float:
    return sum(math.dist(a, b) for a, b in zip(line, line[1:], strict=False))


def exit_point(line: list[XY], radius: float) -> XY | None:
    """Erster Punkt entlang ``line``, an dem der Abstand zum Ursprung ``radius`` erreicht
    (zwischen zwei Stützpunkten linear interpoliert); ``None``, wenn das nie geschieht."""
    for a, b in zip(line, line[1:], strict=False):
        da, db = math.hypot(*a), math.hypot(*b)
        if da >= radius:
            return a
        if db >= radius:
            # Schnitt der Strecke a→b mit dem Kreis: |a + t(b−a)| = radius
            dx, dy = b[0] - a[0], b[1] - a[1]
            qa = dx * dx + dy * dy
            qb = 2 * (a[0] * dx + a[1] * dy)
            qc = da * da - radius * radius
            t = (-qb + math.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa)
            return a[0] + t * dx, a[1] + t * dy
    if line and math.hypot(*line[-1]) >= radius:
        return line[-1]
    return None


@dataclass(frozen=True)
class Projection:
    along_m: float  # Strecke entlang der Linie bis zum Lotfußpunkt
    dist_m: float  # seitlicher Abstand
    within: bool  # Lotfußpunkt zwischen Anfang und Ende der Linie


def project(p: XY, line: list[XY]) -> Projection:
    """Nächster Punkt der Linie zu ``p``. ``within`` ist falsch, wenn der nächste Punkt nur
    durch Abschneiden vor dem Anfang oder hinter dem Ende entsteht."""
    best: tuple[float, float, bool] | None = None
    start = 0.0
    last = len(line) - 2
    for i, (a, b) in enumerate(zip(line, line[1:], strict=False)):
        dx, dy = b[0] - a[0], b[1] - a[1]
        seg = math.hypot(dx, dy)
        t_raw = 0.0 if seg == 0 else ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (seg * seg)
        t = min(1.0, max(0.0, t_raw))
        d = math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
        within = not ((i == 0 and t_raw < 0) or (i == last and t_raw > 1))
        if best is None or d < best[1]:
            best = (start + t * seg, d, within)
        start += seg
    along, dist, within = best
    return Projection(along, dist, within)


def distance_to_line(p: XY, line: list[XY]) -> float:
    if len(line) == 1:
        return math.dist(p, line[0])
    return project(p, line).dist_m
