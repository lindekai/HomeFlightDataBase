"""Datenbankzugriffe von ingest."""

from __future__ import annotations

from pathlib import Path

import psycopg


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
