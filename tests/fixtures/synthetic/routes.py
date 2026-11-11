"""Synthetische An- und Abflüge am erfundenen Flughafen um 50° N / 10° O.

Wegpunkte in der lokalen Ebene (x Ost, y Nord, m) um den Referenzpunkt; dieselbe Projektion
wie in ``analysis.geo``, damit Abstände in Tests exakt sind. ICAO24 beginnt mit ``ff``.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from analysis.geo import XY, Local
from analysis.segment import Point

CENTER = (50.0, 10.0)
LOCAL = Local(*CENTER)
PROCEDURES_FILE = Path(__file__).resolve().parents[1] / "procedures.test.yaml"
KT_TO_MS = 1852 / 3600

# Wegpunkte aus procedures.test.yaml in der lokalen Ebene
THR_27, THR_09 = (1500.0, 0.0), (-1500.0, 0.0)
TWEST, TEAST = (-16000.0, 0.0), (16000.0, 0.0)
WNMID, WNORD = (-20000.0, 20000.0), (-35000.0, 40000.0)
WSMID, WSUED = (-20000.0, -20000.0), (-35000.0, -40000.0)
ONMID, ONORD = (20000.0, 20000.0), (35000.0, 40000.0)
OSMID, OSUED = (20000.0, -20000.0), (35000.0, -40000.0)


def fly(
    waypoints: list[XY],
    start: datetime,
    *,
    speed_kt: float = 250,
    alt_ft: float = 500,
    vrate_fpm: float = 2000,
    step_s: float = 1.0,
    icao24: str = "ff0101",
    callsign: str | None = "TST101",
) -> list[dict]:
    """Positionen entlang der Wegpunktfolge mit fester Geschwindigkeit und Steigrate, im
    Format von ``synthetic.tracks.insert_positions``."""
    speed = speed_kt * KT_TO_MS
    legs = list(zip(waypoints, waypoints[1:], strict=False))
    total = sum(math.dist(a, b) for a, b in legs)
    rows = []
    i = 0
    while speed * step_s * i <= total:
        s = speed * step_s * i
        for a, b in legs:
            d = math.dist(a, b)
            if s <= d:
                f = s / d
                x, y = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
                break
            s -= d
        lat, lon = LOCAL.latlon(x, y)
        rows.append(
            {
                "ts": start + timedelta(seconds=step_s * i),
                "icao24": icao24,
                "callsign": callsign,
                "lat": lat,
                "lon": lon,
                "alt_baro_ft": round(alt_ft + vrate_fpm * step_s * i / 60),
                "baro_rate_fpm": round(vrate_fpm),
                "on_ground": False,
            }
        )
        i += 1
    return rows


def points(rows: list[dict]) -> list[Point]:
    return [
        Point(
            r["ts"],
            r["lat"],
            r["lon"],
            r["alt_baro_ft"],
            r["baro_rate_fpm"],
            r["callsign"],
            r["on_ground"],
        )
        for r in rows
    ]
