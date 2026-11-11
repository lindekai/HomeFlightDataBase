import os
import time

import pytest

from analysis import cli

ENV = {
    "ANALYSIS_DB_DSN": "postgresql://u@127.0.0.1:1/x",
    "ANALYSIS_BER_LAT": "49",
    "ANALYSIS_BER_LON": "8",
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ANALYSIS_ZONES_FILE", raising=False)
    monkeypatch.delenv("ANALYSIS_PROCEDURES_FILE", raising=False)
    hb = tmp_path / "hb"
    monkeypatch.setenv("ANALYSIS_HEARTBEAT_FILE", str(hb))
    monkeypatch.setenv("ANALYSIS_INTERVAL_S", "10")
    return hb


def test_health_without_heartbeat_fails(env):
    assert cli.main(["health"]) == 1


def test_health_with_stale_heartbeat_fails(env):
    env.write_text("")
    old = time.time() - 60
    os.utime(env, (old, old))
    assert cli.main(["health"]) == 1


def test_health_fresh_heartbeat_but_db_unreachable_fails(env):
    env.write_text("")
    assert cli.main(["health"]) == 1


def test_zones_without_file_is_error(env):
    assert cli.main(["zones"]) == 2


def test_procedures_without_file_is_error(env):
    assert cli.main(["procedures"]) == 2


def test_invalid_procedures_file_fails_before_database(env, tmp_path):
    bad = tmp_path / "procedures.yaml"
    bad.write_text("waypoints: []\n", encoding="utf-8")
    assert cli.main(["procedures", str(bad)]) == 1


def test_iteration_runs_analysis_despite_unexpected_procedure_error(
    env, tmp_path, monkeypatch, caplog
):
    procedures = tmp_path / "procedures.yaml"
    procedures.write_text("waypoints: {}\n", encoding="utf-8")
    monkeypatch.setenv("ANALYSIS_PROCEDURES_FILE", str(procedures))
    calls = []

    def broken(cfg, path):
        raise TypeError("Inhalt 50.0 10.0")

    monkeypatch.setattr(cli, "sync_procedures", broken)
    monkeypatch.setattr(cli, "run_once", lambda cfg: calls.append(cfg))
    with caplog.at_level("INFO", logger="analysis"):
        cli._iteration(cli.Config.from_env())

    assert len(calls) == 1
    assert env.is_file()
    messages = [(r.getMessage(), getattr(r, "error", None), r.exc_info) for r in caplog.records]
    assert messages == [
        ("Verfahrensdatei nicht verarbeitet – bisherige Fassung bleibt aktiv", "TypeError", None)
    ]
