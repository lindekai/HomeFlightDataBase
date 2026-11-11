"""readsb-Attrappe: liefert /data/aircraft.json mit synthetischen Flugzeugen (ff0xxx).

Drei Flugzeuge kreisen um 50° N / 10° O (ff0000–ff0002). Dazu fliegen Abflüge (ff0110) und
Anflüge (ff0111) im Takt auf erfundenen Verfahren aus ``procedures.test.yaml`` und einmalig ein
Abflug mit Umweg (ff0112). Rufzeichen wechseln je Umlauf, damit jeder Umlauf ein Flug ist.
"""

from __future__ import annotations

import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from synthetic.generator import aircraft, snapshot

CENTER = (50.0, 10.0)
EARTH_RADIUS_M = 6_371_008.8
KT_TO_MS = 1852 / 3600

# Wegpunkte in m (x Ost, y Nord) um CENTER, wie in procedures.test.yaml
DEPARTURE = [(-1500.0, 0.0), (-16000.0, 0.0), (-20000.0, 20000.0)]  # WNORD1W bis WNMID
DETOUR = [(-1500.0, 0.0), (-16000.0, 0.0), (-23000.0, 6000.0), (-20000.0, 20000.0)]
ARRIVAL = [(23000.0, 24000.0), (20000.0, 20000.0), (16000.0, 0.0), (1500.0, 0.0)]  # ONORD1W

# (hex, Route, kt, Starthöhe ft, ft/min, erster Start s, Takt s oder None = einmalig)
SCHEDULE = [
    ("ff0110", DEPARTURE, 300, 500, 3000, 30, 300),
    ("ff0111", ARRIVAL, 250, 8000, -1500, 60, 360),
    ("ff0112", DETOUR, 300, 500, 3000, 150, None),
]


def latlon(x: float, y: float) -> tuple[float, float]:
    """Lokale Ebene → Grad (gleichabständig; im Umkreis 30 km auf < 100 m genau)."""
    lat = CENTER[0] + math.degrees(y / EARTH_RADIUS_M)
    lon = CENTER[1] + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(CENTER[0]))))
    return lat, lon


def along(route: list[tuple[float, float]], dist: float) -> tuple[float, float] | None:
    for a, b in zip(route, route[1:], strict=False):
        leg = math.dist(a, b)
        if dist <= leg:
            f = dist / leg
            return a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
        dist -= leg
    return None


def scripted(elapsed: float) -> list[dict]:
    """Planmäßige An- und Abflüge ``elapsed`` Sekunden nach dem Start der Attrappe."""
    planes = []
    for hex_, route, kt, alt0, vrate, first, period in SCHEDULE:
        if elapsed < first:
            continue
        cycle, t = (0, elapsed - first) if period is None else divmod(elapsed - first, period)
        pos = along(route, t * kt * KT_TO_MS)
        if pos is None:
            continue
        lat, lon = latlon(*pos)
        planes.append(
            aircraft(
                hex=hex_,
                lat=lat,
                lon=lon,
                alt_baro=round(alt0 + vrate * t / 60),
                seen_pos=0.4,
                flight=f"TST{hex_[-2:]}{int(cycle) % 10}",
                gs=float(kt),
                baro_rate=vrate,
            )
        )
    return planes


def current_snapshot(t: float, started: float | None = None) -> dict:
    planes = []
    for i in range(3):
        angle = (t / 120.0 + i * 2.1) % (2 * math.pi)
        planes.append(
            aircraft(
                hex=f"ff00{i:02x}",
                lat=50.0 + 0.2 * math.sin(angle),
                lon=10.0 + 0.3 * math.cos(angle),
                alt_baro=3000 + 1000 * i,
                seen_pos=0.4,
            )
        )
    if started is not None:
        planes += scripted(t - started)
    return snapshot(round(t, 1), planes)


class Handler(BaseHTTPRequestHandler):
    started = time.time()

    def do_GET(self):
        if self.path != "/data/aircraft.json":
            self.send_error(404)
            return
        body = json.dumps(current_snapshot(time.time(), self.started)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()
