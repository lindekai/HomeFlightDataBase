"""Zonendurchquerungen eines Flugs: Geometrie in PostGIS, Kennwerte in Python."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg

from analysis.classify import classify
from analysis.config import Config
from analysis.segment import Point

SECTORS = ("N", "NO", "O", "SO", "S", "SW", "W", "NW")

# Teilstücke der Spur innerhalb jeder aktuellen Zone; Zeitpunkte über den M-Wert (Unix-Zeit).
# Nächster Punkt geodätisch (geography): planar in Grad wäre er bei schrägen Spuren verschoben.
_CROSSINGS = """
WITH f AS (SELECT track FROM flights WHERE id = %(flight_id)s),
parts AS (
  SELECT z.id, z.ref_point, (ST_Dump(ST_Intersection(ST_Force2D(f.track), z.geom))).geom AS part
  FROM geofences z, f
  WHERE z.valid_to IS NULL AND ST_Intersects(z.geom, f.track)
)
SELECT parts.id,
  ST_InterpolatePoint(f.track, ST_StartPoint(part)),
  ST_InterpolatePoint(f.track, ST_EndPoint(part)),
  ST_Distance(part::geography, ref_point::geography),
  ST_InterpolatePoint(
    f.track, ST_ClosestPoint(part::geography, ref_point::geography)::geometry
  ),
  degrees(ST_Azimuth(ST_StartPoint(part)::geography, ST_EndPoint(part)::geography))
FROM parts, f
WHERE GeometryType(part) = 'LINESTRING'
"""


@dataclass(frozen=True)
class Crossing:
    geofence_id: int
    entry: datetime
    exit: datetime
    closest: datetime
    min_dist_m: float
    heading_deg: float | None


def _ts(m: float) -> datetime:
    return datetime.fromtimestamp(m, UTC)


def crossings(conn: psycopg.Connection, flight_id: int) -> list[Crossing]:
    out = []
    for gid, m_start, m_end, dist, m_closest, heading in conn.execute(
        _CROSSINGS, {"flight_id": flight_id}
    ):
        if m_start > m_end:  # Teilstück entgegen der Flugrichtung geliefert
            m_start, m_end = m_end, m_start
            heading = None if heading is None else (heading + 180) % 360
        out.append(Crossing(gid, _ts(m_start), _ts(m_end), _ts(m_closest), dist, heading))
    return sorted(out, key=lambda c: (c.entry, c.geofence_id))


def sector(heading: float | None) -> str | None:
    if heading is None:
        return None
    return SECTORS[int(((heading % 360) + 22.5) // 45) % 8]


def interp_alt(points: list[Point], ts: datetime) -> float | None:
    """Höhe zum Zeitpunkt ``ts``, linear zwischen den Nachbarpositionen mit Höhe."""
    before = next((p for p in reversed(points) if p.ts <= ts and p.alt_ft is not None), None)
    after = next((p for p in points if p.ts >= ts and p.alt_ft is not None), None)
    if before is None or after is None:
        known = before or after
        return None if known is None else float(known.alt_ft)
    span = (after.ts - before.ts).total_seconds()
    if span == 0:
        return float(before.alt_ft)
    f = (ts - before.ts).total_seconds() / span
    return before.alt_ft + f * (after.alt_ft - before.alt_ft)


def build_event(c: Crossing, points: list[Point], relevance_ft: int, cfg: Config) -> dict:
    inside = [p for p in points if c.entry <= p.ts <= c.exit]
    alts = [float(p.alt_ft) for p in inside if p.alt_ft is not None]
    alts += [a for a in (interp_alt(points, c.entry), interp_alt(points, c.exit)) if a is not None]
    min_alt = round(min(alts)) if alts else None
    at_closest = interp_alt(points, c.closest)

    before = next((p for p in reversed(points) if p.ts <= c.entry), None)
    after = next((p for p in points if p.ts >= c.exit), None)
    seq = [p.ts for p in ([before] if before else []) + inside + ([after] if after else [])]
    gaps = [(b - a).total_seconds() for a, b in zip(seq, seq[1:], strict=False)]

    ctx = timedelta(seconds=cfg.context_s)
    cls = classify(
        [p for p in points if c.entry - ctx <= p.ts <= c.exit + ctx],
        ber_lat=cfg.ber_lat,
        ber_lon=cfg.ber_lon,
        min_positions=cfg.min_positions,
        vrate_fpm=cfg.vrate_fpm,
        ber_radius_m=cfg.ber_radius_m,
    )
    return {
        "geofence_id": c.geofence_id,
        "entry_ts": c.entry,
        "exit_ts": c.exit,
        "duration_s": (c.exit - c.entry).total_seconds(),
        "min_dist_m": c.min_dist_m,
        "closest_ts": c.closest,
        "min_alt_ft": min_alt,
        "alt_at_closest_ft": None if at_closest is None else round(at_closest),
        "heading_deg": c.heading_deg,
        "heading_sector": sector(c.heading_deg),
        "category": cls.category,
        "category_basis": cls.basis,
        "relevant": min_alt is None or min_alt <= relevance_ft,
        "n_positions_inside": len(inside),
        "max_position_gap_s": max(gaps) if gaps else None,
    }
