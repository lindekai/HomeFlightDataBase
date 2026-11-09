import subprocess
import time
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.e2e

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parent / "compose.yml")]
DSN = "postgresql://flightdb_admin:admin@localhost:55433/flightdb"


@pytest.fixture(scope="module")
def stack():
    subprocess.run([*COMPOSE, "up", "-d", "--build"], check=True)
    try:
        yield
    finally:
        subprocess.run([*COMPOSE, "logs", "--no-color", "recorder", "ingest"], check=False)
        subprocess.run([*COMPOSE, "down", "-v"], check=True)


def query(sql):
    with psycopg.connect(DSN) as c:
        return c.execute(sql).fetchone()


def wait_for(condition, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if condition():
                return
        except psycopg.Error:
            pass
        time.sleep(3)
    pytest.fail("Zeitüberschreitung beim Warten")


def receiver_exec(*cmd):
    return subprocess.run(
        [*COMPOSE, "exec", "-T", "receiver-ssh", *cmd],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def receiver_digests():
    out = receiver_exec("sh", "-c", "find /data/complete -name '*.sha256' -exec cat {} +")
    return {line.split()[0] for line in out.splitlines() if line.strip()}


def ingested_digests():
    with psycopg.connect(DSN) as c:
        return {r[0] for r in c.execute("SELECT sha256 FROM raw_files WHERE status = 'ingested'")}


def test_pipeline_end_to_end(stack):
    wait_for(lambda: query("SELECT count(*) FROM raw_files WHERE status = 'ingested'")[0] >= 3)

    total, distinct = query(
        "SELECT count(*), count(DISTINCT (receiver_id, icao24, ts)) FROM positions"
    )
    assert total > 0 and total == distinct
    assert query("SELECT count(DISTINCT icao24) FROM positions")[0] == 3
    assert query("SELECT count(*) FROM raw_files WHERE receiver_id <> 'TEST'")[0] == 0

    acks = receiver_exec("find", "/data/acked", "-name", "*.ack").split()
    assert len(acks) >= 3


def test_connection_outage_loses_nothing(stack):
    subprocess.run([*COMPOSE, "stop", "receiver-ssh"], check=True)
    time.sleep(30)  # recorder schreibt weiter, ingest erreicht den Pi nicht
    subprocess.run([*COMPOSE, "start", "receiver-ssh"], check=True)

    expected = receiver_digests()
    assert len(expected) >= 5
    wait_for(lambda: expected <= ingested_digests())
