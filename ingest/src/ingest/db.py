"""Datenbankzugriffe von ingest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from psycopg import sql

from ingest.parse import POSITION_FIELDS, ParsedFile


def migrate(conn: psycopg.Connection, migrations_dir: Path) -> list[str]:
    """Spielt noch nicht angewendete SQL-Dateien in Namensreihenfolge ein."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


def _month_start(ts: datetime) -> datetime:
    ts = ts.astimezone(UTC)
    return datetime(ts.year, ts.month, 1, tzinfo=UTC)


def _next_month(m: datetime) -> datetime:
    return datetime(m.year + m.month // 12, m.month % 12 + 1, 1, tzinfo=UTC)


def ensure_partitions(conn: psycopg.Connection, start: datetime, end: datetime) -> list[str]:
    """Legt fehlende Monatspartitionen von ``positions`` für [start, end] an (Admin-Rolle)."""
    created = []
    month = _month_start(start)
    while month <= end:
        nxt = _next_month(month)
        name = f"positions_y{month:%Y}m{month:%m}"
        if conn.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is None:
            conn.execute(
                sql.SQL(
                    "CREATE TABLE {} PARTITION OF positions FOR VALUES FROM ({}) TO ({})"
                ).format(sql.Identifier(name), sql.Literal(month), sql.Literal(nxt))
            )
            created.append(name)
        month = nxt
    return created


def ensure_receiver(conn: psycopg.Connection, receiver_id: str) -> None:
    conn.execute(
        "INSERT INTO receivers (id, label) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
        (receiver_id, receiver_id),
    )


def register_raw_file(
    conn: psycopg.Connection,
    *,
    receiver_id: str,
    path: str,
    sha256: str,
    size_bytes: int,
    partial: bool,
    version: str,
) -> tuple[int, str]:
    """Registriert eine Rohdatei; bei bekannter Prüfsumme wird der vorhandene Eintrag geliefert.

    Gleicher Pfad mit anderer Prüfsumme löst ``UniqueViolation`` aus.
    """
    row = conn.execute(
        """
        INSERT INTO raw_files
            (receiver_id, path, sha256, size_bytes, partial, status, ingest_version)
        VALUES (%s, %s, %s, %s, %s, 'registered', %s)
        ON CONFLICT (sha256) DO UPDATE SET sha256 = EXCLUDED.sha256
        RETURNING id, status
        """,
        (receiver_id, path, sha256, size_bytes, partial, version),
    ).fetchone()
    return row[0], row[1]


def find_raw_file(conn: psycopg.Connection, sha256: str) -> int | None:
    row = conn.execute("SELECT id FROM raw_files WHERE sha256 = %s", (sha256,)).fetchone()
    return None if row is None else row[0]


_TMP_COLUMNS = """
    ts timestamptz, icao24 text, callsign text, lon double precision, lat double precision,
    on_ground boolean, alt_baro_ft integer, alt_geom_ft integer, gs_kt real, track_deg real,
    baro_rate_fpm integer, squawk text, source_type text, nic smallint, nac_p smallint,
    sil smallint, rssi_dbfs real
"""

_INSERT_POSITIONS = """
    INSERT INTO positions (ts, receiver_id, icao24, callsign, geom, on_ground, alt_baro_ft,
        alt_geom_ft, gs_kt, track_deg, baro_rate_fpm, squawk, source_type, nic, nac_p, sil,
        rssi_dbfs, raw_file_id)
    SELECT ts, %(receiver_id)s, icao24, callsign, ST_SetSRID(ST_MakePoint(lon, lat), 4326),
        on_ground, alt_baro_ft, alt_geom_ft, gs_kt, track_deg, baro_rate_fpm, squawk,
        source_type, nic, nac_p, sil, rssi_dbfs, %(raw_file_id)s
    FROM tmp_positions
    ON CONFLICT DO NOTHING
"""

_UPSERT_AIRCRAFT = """
    INSERT INTO aircraft (icao24, registration, type_code, first_seen, last_seen)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (icao24) DO UPDATE SET
        registration = coalesce(EXCLUDED.registration, aircraft.registration),
        type_code = coalesce(EXCLUDED.type_code, aircraft.type_code),
        first_seen = least(aircraft.first_seen, EXCLUDED.first_seen),
        last_seen = greatest(aircraft.last_seen, EXCLUDED.last_seen)
"""


def load_parsed(conn: psycopg.Connection, raw_file_id: int, parsed: ParsedFile) -> int:
    """Lädt eine Datei in einer Transaktion; gibt die Zahl neu eingefügter Positionen zurück."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE tmp_positions ({_TMP_COLUMNS}) ON COMMIT DROP")
        with cur.copy(f"COPY tmp_positions ({', '.join(POSITION_FIELDS)}) FROM STDIN") as copy:
            for p in parsed.positions:
                copy.write_row(tuple(getattr(p, f) for f in POSITION_FIELDS))
        cur.execute(
            _INSERT_POSITIONS, {"receiver_id": parsed.receiver_id, "raw_file_id": raw_file_id}
        )
        inserted = cur.rowcount
        cur.executemany(
            "INSERT INTO reception_gaps (receiver_id, gap_start, gap_end, reason, raw_file_id)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(parsed.receiver_id, g.start, g.end, g.reason, raw_file_id) for g in parsed.gaps],
        )
        cur.executemany(
            _UPSERT_AIRCRAFT,
            [
                (a.icao24, a.registration, a.type_code, a.first_seen, a.last_seen)
                for a in parsed.aircraft.values()
            ],
        )
        cur.execute(
            """
            UPDATE raw_files SET status = 'ingested', error = NULL, period_start = %s,
                period_end = %s, clock_offset_max_s = %s, receiver_free_bytes = %s
            WHERE id = %s
            """,
            (
                parsed.period_start,
                parsed.period_end,
                parsed.clock_offset_max_s,
                parsed.receiver_free_bytes,
                raw_file_id,
            ),
        )
    return inserted


def mark_failed(conn: psycopg.Connection, raw_file_id: int, error: str) -> None:
    conn.execute(
        "UPDATE raw_files SET status = 'failed', error = %s WHERE id = %s", (error, raw_file_id)
    )


def pending_files(conn: psycopg.Connection) -> list[tuple[int, str, str]]:
    return conn.execute(
        "SELECT id, path, sha256 FROM raw_files"
        " WHERE status IN ('registered', 'failed') ORDER BY id"
    ).fetchall()


def delete_file_data(conn: psycopg.Connection, raw_file_id: int) -> None:
    """Entfernt Positionen und Lücken einer Datei (für ``rebuild``); Archiv bleibt unberührt."""
    start, end = conn.execute(
        "SELECT period_start, period_end FROM raw_files WHERE id = %s", (raw_file_id,)
    ).fetchone()
    with conn.transaction():
        if start is not None:
            # Positionszeitpunkte liegen um seen_pos vor recorder_ts; Puffer von 5 Minuten.
            conn.execute(
                "DELETE FROM positions WHERE raw_file_id = %s AND ts >= %s AND ts <= %s",
                (raw_file_id, start - timedelta(minutes=5), end),
            )
        conn.execute("DELETE FROM reception_gaps WHERE raw_file_id = %s", (raw_file_id,))
        conn.execute("UPDATE raw_files SET status = 'registered' WHERE id = %s", (raw_file_id,))
