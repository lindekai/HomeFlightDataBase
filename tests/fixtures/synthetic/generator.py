"""Erzeugt aircraft.json-Daten im readsb-Format.

Alle ICAO24-Kennungen beginnen mit ``ff``, Koordinaten sind frei gewählt,
jede Momentaufnahme trägt ``"synthetic": true``.
"""

from __future__ import annotations


def aircraft(
    hex: str = "ff0001",
    lat: float = 50.0,
    lon: float = 10.0,
    seen_pos: float | None = 0.5,
    alt_baro: int | str = 3000,
    **extra,
) -> dict:
    ac = {
        "hex": hex,
        "type": "adsb_icao",
        "flight": "TEST01  ",
        "r": "TEST-REG",
        "t": "TST1",
        "alt_baro": alt_baro,
        "alt_geom": alt_baro + 100 if isinstance(alt_baro, int) else None,
        "gs": 180.0,
        "track": 90.0,
        "baro_rate": 0,
        "squawk": "7000",
        "lat": lat,
        "lon": lon,
        "nic": 8,
        "nac_p": 9,
        "sil": 3,
        "seen_pos": seen_pos,
        "seen": 0.1,
        "rssi": -20.5,
    }
    ac.update(extra)
    return {k: v for k, v in ac.items() if v is not None}


def snapshot(now: float, planes: list[dict]) -> dict:
    return {"now": now, "messages": 1000, "synthetic": True, "aircraft": planes}
