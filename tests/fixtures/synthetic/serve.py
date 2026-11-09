"""readsb-Attrappe: liefert /data/aircraft.json mit drei synthetischen Flugzeugen (ff00xx)."""

from __future__ import annotations

import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from synthetic.generator import aircraft, snapshot


def current_snapshot(t: float) -> dict:
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
    return snapshot(round(t, 1), planes)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/data/aircraft.json":
            self.send_error(404)
            return
        body = json.dumps(current_snapshot(time.time())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()
