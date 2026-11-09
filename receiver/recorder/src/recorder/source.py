"""Abruf der aktuellen Flugzeugliste von readsb."""

from __future__ import annotations

import http.client
import json
import urllib.request


def fetch_aircraft(url: str, timeout: float = 2.0) -> dict | None:
    """Liest ``aircraft.json``. Gibt ``None`` zurück, wenn nichts Verwertbares kommt."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("now"), int | float):
        return None
    return data
