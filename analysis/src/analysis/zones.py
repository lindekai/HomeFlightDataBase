"""Überwachungszonen: GeoJSON lesen und prüfen, mit ``geofences`` abgleichen.

Kreise (Point + ``radius_m``) werden in PostGIS geodätisch in ein 64-Eck umgerechnet.
Geänderte Zonen erhalten eine neue Fassung; die alte wird mit ``valid_to`` geschlossen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import psycopg


class ZoneError(ValueError):
    pass


@dataclass(frozen=True)
class Zone:
    name: str
    kind: str  # circle | polygon
    geometry: dict
    radius_m: float | None
    ref_point: tuple[float, float] | None  # (lon, lat)
    relevance_max_alt_ft: int
    source: str | None


@dataclass(frozen=True)
class ZoneSync:
    changed: list[str]
    removed: list[str]


def _lonlat(value, what: str) -> tuple[float, float]:
    if (
        not isinstance(value, list | tuple)
        or len(value) < 2
        or not all(isinstance(v, int | float) for v in value[:2])
        or not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90)
    ):
        raise ZoneError(f"{what}: [lon, lat] erwartet")
    return float(value[0]), float(value[1])


def parse_zones(data: dict, default_relevance_ft: int) -> list[Zone]:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ZoneError("GeoJSON FeatureCollection erwartet")
    zones: list[Zone] = []
    for i, feature in enumerate(data.get("features") or []):
        props = feature.get("properties") or {}
        name = props.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ZoneError(f"Feature {i}: Property name fehlt")
        if any(z.name == name for z in zones):
            raise ZoneError(f"Zone {name!r} doppelt")
        geometry = feature.get("geometry") or {}
        gtype = geometry.get("type")
        if gtype == "Point":
            radius = props.get("radius_m")
            if not isinstance(radius, int | float) or radius <= 0:
                raise ZoneError(f"{name}: Kreis braucht radius_m > 0")
            kind, radius_m = "circle", float(radius)
            ref = _lonlat(geometry.get("coordinates"), f"{name}: Mittelpunkt")
        elif gtype in ("Polygon", "MultiPolygon"):
            kind, radius_m = "polygon", None
            ref = props.get("ref_point")
            ref = None if ref is None else _lonlat(ref, f"{name}: ref_point")
        else:
            raise ZoneError(f"{name}: Typ {gtype!r} nicht unterstützt")
        zones.append(
            Zone(
                name=name,
                kind=kind,
                geometry=geometry,
                radius_m=radius_m,
                ref_point=ref,
                relevance_max_alt_ft=int(props.get("relevance_max_alt_ft", default_relevance_ft)),
                source=props.get("source"),
            )
        )
    if not zones:
        raise ZoneError("keine Zonen definiert")
    return zones


def read_zones(path: Path, default_relevance_ft: int) -> list[Zone]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ZoneError(f"{path}: kein gültiges JSON ({e})") from e
    return parse_zones(data, default_relevance_ft)


_GEOM = """
SELECT s.g, coalesce(ST_SetSRID(ST_MakePoint(%(ref_lon)s::float8, %(ref_lat)s::float8), 4326),
                     ST_PointOnSurface(s.g)),
       ST_IsValid(s.g), ST_IsValidReason(s.g)
FROM (
  SELECT CASE WHEN %(kind)s = 'circle'
    THEN ST_Multi(ST_Buffer(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)::geography,
                            %(radius_m)s::float8, 'quad_segs=16')::geometry)
    ELSE ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326))
  END AS g
) s
"""

_CURRENT = """
SELECT id,
       ST_Equals(geom, %(g)s::geometry) AND ST_Equals(ref_point, %(ref)s::geometry)
       AND kind = %(kind)s AND radius_m IS NOT DISTINCT FROM %(radius_m)s::real
       AND relevance_max_alt_ft = %(relevance)s AND source IS NOT DISTINCT FROM %(source)s
FROM geofences WHERE name = %(name)s AND valid_to IS NULL
"""

_INSERT = """
INSERT INTO geofences (name, kind, geom, ref_point, radius_m, relevance_max_alt_ft, source)
VALUES (%(name)s, %(kind)s, %(g)s::geometry, %(ref)s::geometry, %(radius_m)s,
        %(relevance)s, %(source)s)
"""


def load_zones(conn: psycopg.Connection, zones: list[Zone]) -> ZoneSync:
    """Gleicht alle Zonen in einer Transaktion ab; fehlende Zonen werden geschlossen."""
    changed: list[str] = []
    with conn.transaction():
        for z in zones:
            params = {
                "name": z.name,
                "kind": z.kind,
                "geometry": json.dumps(z.geometry),
                "radius_m": z.radius_m,
                "ref_lon": None if z.ref_point is None else z.ref_point[0],
                "ref_lat": None if z.ref_point is None else z.ref_point[1],
                "relevance": z.relevance_max_alt_ft,
                "source": z.source,
            }
            try:
                g, ref, valid, reason = conn.execute(_GEOM, params).fetchone()
            except psycopg.errors.DataException as e:
                raise ZoneError(f"{z.name}: Geometrie ungültig ({e})") from e
            if not valid:
                raise ZoneError(f"{z.name}: Geometrie ungültig ({reason})")
            params |= {"g": g, "ref": ref}
            current = conn.execute(_CURRENT, params).fetchone()
            if current and current[1]:
                continue
            if current:
                conn.execute("UPDATE geofences SET valid_to = now() WHERE id = %s", (current[0],))
            conn.execute(_INSERT, params)
            changed.append(z.name)
        removed = conn.execute(
            "UPDATE geofences SET valid_to = now()"
            " WHERE valid_to IS NULL AND NOT (name = ANY(%s)) RETURNING name",
            ([z.name for z in zones],),
        ).fetchall()
    return ZoneSync(changed, sorted(r[0] for r in removed))
