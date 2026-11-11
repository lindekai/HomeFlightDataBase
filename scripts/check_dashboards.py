#!/usr/bin/env python3
"""Prüft Grafana-Dashboards auf Ortsangaben (öffentliches Repo).

Karten müssen die Ansicht „Fit to data“ (``view.id == "fit"``) nutzen; Zahlenwerte unter
Schlüsseln wie lat/lon/zoom/center sind verboten. Feldnamen (Zeichenketten) sind erlaubt.
Aufruf: python scripts/check_dashboards.py dashboard/dashboards/*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FORBIDDEN = {"lat", "lon", "lng", "latitude", "longitude", "zoom", "center"}


def problems(obj, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        if obj.get("type") == "geomap":
            view = (obj.get("options") or {}).get("view") or {}
            if view.get("id") != "fit":
                found.append(f"{path}: Kartenansicht muss 'fit' sein")
        for key, value in obj.items():
            if key.lower() in FORBIDDEN and not isinstance(value, str | bool):
                found.append(f"{path}.{key}: Koordinaten oder Zoom nicht erlaubt")
            found += problems(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found += problems(value, f"{path}[{i}]")
    return found


def main(argv: list[str]) -> int:
    failed = 0
    for name in argv:
        for problem in problems(json.loads(Path(name).read_text(encoding="utf-8"))):
            print(f"{name}: {problem}", file=sys.stderr)
            failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
