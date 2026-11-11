"""Synthetische Flugspuren direkt in ``positions`` (ohne Rohdateien) für Analyse-Tests.

Koordinaten um 50° N / 10° O sind frei gewählt; ICAO24 beginnt mit ``ff``.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta

import psycopg

from ingest.db import ensure_partitions, ensure_receiver

A = 6_378_137.0
E2 = 6.69437999014e-3
KT_TO_MS = 1852 / 3600


def m_per_deg(lat: float) -> tuple[float, float]:
    """Meter je Grad Breite und Länge auf dem WGS84-Ellipsoid."""
    s = math.sin(math.radians(lat)) ** 2
    w = math.sqrt(1 - E2 * s)
    return (
        math.pi * A * (1 - E2) / (180 * w**3),
        math.pi * A * math.cos(math.radians(lat)) / (180 * w),
    )


def offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    m_lat, m_lon = m_per_deg(lat)
    return lat + north_m / m_lat, lon + east_m / m_lon


def straight(
    start: datetime,
    lat: float,
    lon: float,
    heading_deg: float,
    speed_kt: float,
    n: int,
    *,
    step_s: float = 1.0,
    alt_ft: int | None = 3000,
    vrate_fpm: int = 0,
    icao24: str = "ff0001",
    callsign: str | None = "TEST01",
) -> list[dict]:
    """``n`` Positionen im Abstand ``step_s`` mit konstantem Kurs (lokal linear)."""
    m_lat, m_lon = m_per_deg(lat)
    h = math.radians(heading_deg)
    rows = []
    for i in range(n):
        d = speed_kt * KT_TO_MS * step_s * i
        rows.append(
            {
                "ts": start + timedelta(seconds=step_s * i),
                "icao24": icao24,
                "callsign": callsign,
                "lat": lat + d * math.cos(h) / m_lat,
                "lon": lon + d * math.sin(h) / m_lon,
                "alt_baro_ft": None
                if alt_ft is None
                else round(alt_ft + vrate_fpm * step_s * i / 60),
                "baro_rate_fpm": None if alt_ft is None else vrate_fpm,
                "on_ground": False,
            }
        )
    return rows


def insert_positions(dsn: str, rows: list[dict], receiver_id: str = "TEST") -> None:
    with psycopg.connect(dsn, autocommit=True) as c:
        ensure_receiver(c, receiver_id)
        ensure_partitions(c, min(r["ts"] for r in rows), max(r["ts"] for r in rows))
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO positions (ts, receiver_id, icao24, callsign, geom, on_ground,"
                " alt_baro_ft, baro_rate_fpm, raw_file_id) VALUES (%(ts)s, %(rid)s, %(icao24)s,"
                " %(callsign)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326), %(on_ground)s,"
                " %(alt_baro_ft)s, %(baro_rate_fpm)s, 0)",
                [r | {"rid": receiver_id} for r in rows],
            )


def add_raw_file(
    dsn: str,
    start: datetime,
    end: datetime,
    status: str = "ingested",
    receiver_id: str = "TEST",
) -> int:
    """Eintrag in ``raw_files``; bei anderem Status als ``ingested`` ohne Zeitraum."""
    ingested = status == "ingested"
    with psycopg.connect(dsn, autocommit=True) as c:
        ensure_receiver(c, receiver_id)
        return c.execute(
            "INSERT INTO raw_files (receiver_id, path, sha256, size_bytes, period_start,"
            " period_end, status, ingest_version) VALUES (%s, %s, %s, 1, %s, %s, %s, 'test')"
            " RETURNING id",
            (
                receiver_id,
                f"{receiver_id}/{start:%Y/%m/%d}/{start:%Y%m%dT%H%M%SZ}.ndjson.gz",
                uuid.uuid4().hex * 2,
                start if ingested else None,
                end if ingested else None,
                status,
            ),
        ).fetchone()[0]
