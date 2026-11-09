import psycopg
import pytest
from conftest import MIGRATIONS

from ingest.db import migrate

pytestmark = pytest.mark.db


def test_migrate_is_idempotent(db_dsns):
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        assert migrate(c, MIGRATIONS) == []
        versions = [r[0] for r in c.execute("SELECT version FROM schema_migrations")]
        assert versions == ["001_erfassung.sql"]


def test_positions_is_partitioned(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c:
        kind = c.execute("SELECT relkind FROM pg_class WHERE relname = 'positions'").fetchone()
        assert kind == ("p",)


def test_reader_cannot_write(db_dsns):
    with psycopg.connect(db_dsns["reader"]) as c:
        assert c.execute("SELECT count(*) FROM ingest_status").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO receivers (id, label) VALUES ('X', 'x')")


def test_ingest_can_write_receivers(db_dsns):
    with psycopg.connect(db_dsns["ingest"]) as c:
        c.execute("INSERT INTO receivers (id, label) VALUES ('TEST', 'Test')")
        c.commit()
