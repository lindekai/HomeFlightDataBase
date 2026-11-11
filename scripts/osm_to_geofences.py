#!/usr/bin/env python3
"""Wandelt ein Overpass-Ergebnis (``out geom;``) in die Zonendatei für analysis um.

Beispiel (Ausgabe nur nach config/local/, nie committen):
  python scripts/osm_to_geofences.py config/local/overpass.json \
      --source "OSM, ODbL, Abruf JJJJ-MM-TT" --circle "Nahbereich,<lat>,<lon>,1500" \
      > config/local/geofences.geojson

OpenStreetMap-Daten stehen unter der ODbL; die Quelle steht je Zone in ``source``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

Coord = tuple[float, float]  # (lon, lat)


def rings(ways: list[list[Coord]]) -> list[list[Coord]]:
    """Fügt Wegstücke über gemeinsame Endpunkte zu geschlossenen Ringen zusammen."""
    pending = [list(w) for w in ways if len(w) >= 2]
    result: list[list[Coord]] = []
    while pending:
        ring = pending.pop(0)
        while ring[0] != ring[-1]:
            for i, w in enumerate(pending):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[-2::-1]
                else:
                    continue
                pending.pop(i)
                break
            else:
                raise ValueError("Grenze nicht geschlossen – Overpass-Ergebnis unvollständig?")
        result.append(ring)
    return result


def _inside(point: Coord, ring: list[Coord]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _polygon(relation: dict) -> dict:
    by_role: dict[str, list[list[Coord]]] = {"outer": [], "inner": []}
    for m in relation.get("members", []):
        if m.get("type") == "way" and m.get("role") in by_role and m.get("geometry"):
            by_role[m["role"]].append([(g["lon"], g["lat"]) for g in m["geometry"]])
    outers = rings(by_role["outer"])
    polygons = [[outer] for outer in outers]
    for inner in rings(by_role["inner"]):
        for poly in polygons:
            if _inside(inner[0], poly[0]):
                poly.append(inner)
                break
    coords = [[[list(c) for c in r] for r in poly] for poly in polygons]
    if len(coords) == 1:
        return {"type": "Polygon", "coordinates": coords[0]}
    return {"type": "MultiPolygon", "coordinates": coords}


def convert(overpass: dict, *, source: str, circles: list[str], relevance_ft: int | None) -> dict:
    extra = {} if relevance_ft is None else {"relevance_max_alt_ft": relevance_ft}
    features = []
    for el in overpass.get("elements", []):
        if el.get("type") != "relation":
            continue
        name = (el.get("tags") or {}).get("name")
        if not name:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": _polygon(el),
                "properties": {"name": name, "source": source, **extra},
            }
        )
    for spec in circles:
        name, lat, lon, radius = spec.rsplit(",", 3)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                "properties": {
                    "name": name.strip(),
                    "radius_m": float(radius),
                    "source": "eigener Kreis",
                    **extra,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("overpass", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument(
        "--circle", action="append", default=[], help='"Name,lat,lon,radius_m" (mehrfach möglich)'
    )
    parser.add_argument("--relevance-ft", type=int)
    args = parser.parse_args(argv)
    data = json.loads(args.overpass.read_text(encoding="utf-8"))
    out = convert(data, source=args.source, circles=args.circle, relevance_ft=args.relevance_ft)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
