import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import conninfo

MIGRATIONS = Path(__file__).resolve().parents[1] / "database" / "migrations"


@pytest.fixture
def db_dsns():
    """Eigene, migrierte Wegwerf-Datenbank je Test; benötigt TEST_ADMIN_DSN."""
    admin = os.environ.get("TEST_ADMIN_DSN")
    if not admin:
        pytest.skip("TEST_ADMIN_DSN nicht gesetzt")
    from ingest.db import migrate

    name = f"flightdb_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    params = conninfo.conninfo_to_dict(admin) | {"dbname": name}
    admin_dsn = conninfo.make_conninfo(**params)
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        migrate(c, MIGRATIONS)
        c.execute("ALTER ROLE flightdb_ingest LOGIN PASSWORD 'test'")
        c.execute("ALTER ROLE flightdb_reader LOGIN PASSWORD 'test'")
        c.execute("ALTER ROLE flightdb_analysis LOGIN PASSWORD 'test'")

    def as_role(role):
        return conninfo.make_conninfo(**(params | {"user": role, "password": "test"}))

    yield {
        "admin": admin_dsn,
        "ingest": as_role("flightdb_ingest"),
        "reader": as_role("flightdb_reader"),
        "analysis": as_role("flightdb_analysis"),
    }
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
