"""Datenbankzugriffe von analysis (Rolle flightdb_analysis)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby
from operator import itemgetter

import psycopg
from psycopg.types.json import Jsonb

from analysis.segment import Point, Segment

LOCK_KEY = 720301  # Advisory-Lock: nur ein Lauf gleichzeitig
_FILE_START = re.compile(r"(\d{8}T\d{6}Z)")


@dataclass
class Counts:
    flights: int = 0
    events: int = 0
    skipped: int = 0


def schema_ready(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT to_regclass('analysis_runs')").fetchone()[0] is not None


def try_lock(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]


def unlock(conn: psycopg.Connection) -> None:
    conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def start_run(
    conn: psycopg.Connection,
    kind: str,
    version: str,
    params: dict,
    window_from: datetime,
    window_to: datetime,
) -> int:
    return conn.execute(
        "INSERT INTO analysis_runs (kind, algo_version, params, window_from, window_to, status)"
        " VALUES (%s, %s, %s, %s, %s, 'running') RETURNING id",
        (kind, version, Jsonb(params), window_from, window_to),
    ).fetchone()[0]


def finish_run(
    conn: psycopg.Connection, run_id: int, status: str, counts: Counts, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE analysis_runs SET status = %s, finished_at = now(), n_flights = %s,"
        " n_events = %s, n_skipped = %s, error = %s WHERE id = %s",
        (status, counts.flights, counts.events, counts.skipped, error, run_id),
    )


def last_incremental(conn: psycopg.Connection) -> tuple[datetime, datetime] | None:
    """(window_to, started_at) des letzten erfolgreichen inkrementellen Laufs."""
    return conn.execute(
        "SELECT window_to, started_at FROM analysis_runs"
        " WHERE kind = 'incremental' AND status = 'ok' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def data_end(conn: psycopg.Connection) -> datetime | None:
    return conn.execute(
        "SELECT max(period_end) FROM raw_files WHERE status = 'ingested'"
    ).fetchone()[0]


@dataclass(frozen=True)
class PendingFile:
    path: str
    status: str
    start: datetime  # Beginn laut Dateiname
    waiting_s: float  # Zeit seit der Registrierung


def pending_files(conn: psycopg.Connection) -> list[PendingFile]:
    """Registrierte, noch nicht eingelesene Dateien (auch ``failed``) mit Beginn aus dem
    Dateinamen."""
    out = []
    for path, status, waiting in conn.execute(
        "SELECT path, status, extract(epoch FROM now() - fetched_at)::float8 FROM raw_files"
        " WHERE status <> 'ingested'"
    ):
        m = _FILE_START.search(path.rsplit("/", 1)[-1])
        if m:
            start = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            out.append(PendingFile(path, status, start, waiting))
    return out


def first_data_start(conn: psycopg.Connection) -> datetime | None:
    return conn.execute(
        "SELECT min(period_start) FROM raw_files WHERE status = 'ingested'"
    ).fetchone()[0]


def late_start(conn: psycopg.Connection, since: datetime, before: datetime) -> datetime | None:
    """Frühester Beginn von Dateien, die seit ``since`` registriert wurden und vor ``before``
    liegen (Nachlieferung)."""
    return conn.execute(
        "SELECT min(period_start) FROM raw_files"
        " WHERE status = 'ingested' AND fetched_at >= %s AND period_start < %s",
        (since, before),
    ).fetchone()[0]


def first_position_ts(conn: psycopg.Connection) -> datetime | None:
    return conn.execute("SELECT min(ts) FROM positions").fetchone()[0]


def delete_flights(
    conn: psycopg.Connection, *, last_from: datetime, first_to: datetime | None = None
) -> dict[str, tuple[datetime, datetime]]:
    """Löscht Flüge (samt Ereignissen); liefert je Flugzeug frühesten Beginn und spätestes Ende."""
    rows = conn.execute(
        "DELETE FROM flights WHERE last_ts >= %s"
        " AND (%s::timestamptz IS NULL OR first_ts <= %s) RETURNING icao24, first_ts, last_ts",
        (last_from, first_to, first_to),
    ).fetchall()
    out: dict[str, tuple[datetime, datetime]] = {}
    for icao, first, last in rows:
        lo, hi = out.get(icao, (first, last))
        out[icao] = (min(lo, first), max(hi, last))
    return out


_POINTS = """
SELECT p.icao24, p.ts, ST_Y(p.geom), ST_X(p.geom), p.alt_baro_ft, p.baro_rate_fpm,
       p.callsign, p.on_ground
FROM positions p
LEFT JOIN unnest(%(icaos)s::text[], %(starts)s::timestamptz[], %(ends)s::timestamptz[])
  AS r(icao24, s, e) ON r.icao24 = p.icao24
WHERE p.ts >= %(lo)s AND p.ts <= %(hi)s
  AND p.ts >= coalesce(r.s, %(start)s) AND p.ts <= coalesce(r.e, %(end)s)
ORDER BY p.icao24, p.ts
"""


def aircraft_points(
    conn: psycopg.Connection,
    start: datetime,
    end: datetime,
    ranges: dict[str, tuple[datetime, datetime]],
) -> Iterator[tuple[str, list[Point]]]:
    """Positionen je Flugzeug, zeitlich sortiert; ``ranges`` überschreibt das Zeitfenster
    einzelner Flugzeuge. Bei mehreren Empfängern zählt je Zeitpunkt eine Position."""
    params = {
        "icaos": list(ranges),
        "starts": [r[0] for r in ranges.values()],
        "ends": [r[1] for r in ranges.values()],
        "start": start,
        "end": end,
        "lo": min([start, *(r[0] for r in ranges.values())]),
        "hi": max([end, *(r[1] for r in ranges.values())]),
    }
    with conn.cursor(name="analysis_positions") as cur:
        cur.itersize = 5000
        cur.execute(_POINTS, params)
        for icao, rows in groupby(cur, key=itemgetter(0)):
            points: list[Point] = []
            for _, ts, lat, lon, alt, vrate, callsign, ground in rows:
                if points and points[-1].ts == ts:
                    continue
                points.append(Point(ts, lat, lon, alt, vrate, callsign, ground))
            yield icao, points


def current_zones(conn: psycopg.Connection) -> dict[int, int]:
    return dict(
        conn.execute("SELECT id, relevance_max_alt_ft FROM geofences WHERE valid_to IS NULL")
    )


def insert_flight(conn: psycopg.Connection, run_id: int, seg: Segment) -> int:
    coords = ", ".join(f"{p.lon} {p.lat} {p.ts.timestamp()}" for p in seg.points)
    return conn.execute(
        "INSERT INTO flights (icao24, callsign, first_ts, last_ts, n_positions, n_outliers,"
        " track, analysis_run_id) VALUES (%s, %s, %s, %s, %s, %s, ST_GeomFromEWKT(%s), %s)"
        " RETURNING id",
        (
            seg.icao24,
            seg.callsign,
            seg.first_ts,
            seg.last_ts,
            len(seg.points),
            seg.n_outliers,
            f"SRID=4326;LINESTRING M ({coords})",
            run_id,
        ),
    ).fetchone()[0]


def in_reception_gap(conn: psycopg.Connection, start: datetime, end: datetime) -> bool:
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM reception_gaps WHERE gap_start < %s AND gap_end > %s)",
        (end, start),
    ).fetchone()[0]


_EVENT_COLUMNS = (
    "geofence_id",
    "entry_ts",
    "exit_ts",
    "duration_s",
    "min_dist_m",
    "closest_ts",
    "min_alt_ft",
    "alt_at_closest_ft",
    "heading_deg",
    "heading_sector",
    "category",
    "category_basis",
    "relevant",
    "n_positions_inside",
    "max_position_gap_s",
    "in_reception_gap",
)


def insert_event(conn: psycopg.Connection, run_id: int, flight_id: int, event: dict) -> None:
    values = event | {"category_basis": Jsonb(event["category_basis"])}
    cols = ", ".join(_EVENT_COLUMNS)
    marks = ", ".join(f"%({c})s" for c in _EVENT_COLUMNS)
    conn.execute(
        f"INSERT INTO overflight_events (flight_id, analysis_run_id, {cols})"
        f" VALUES (%(flight_id)s, %(run_id)s, {marks})",
        values | {"flight_id": flight_id, "run_id": run_id},
    )
