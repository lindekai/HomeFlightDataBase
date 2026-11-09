"""Kommandozeile: ``python -m ingest {run|once|migrate|rebuild|health}``."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

import psycopg

from ingest import __version__
from ingest.config import Config
from ingest.db import migrate
from ingest.logjson import setup_logging
from ingest.pipeline import rebuild, run_once

log = logging.getLogger("ingest")

HEALTH_MAX_AGE_S = 900


def _date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _migrate(cfg: Config) -> None:
    with psycopg.connect(cfg.admin_dsn, autocommit=True) as conn:
        for name in migrate(conn, cfg.migrations_dir):
            log.info("Migration eingespielt", extra={"migration": name})


def _health() -> int:
    work = Config.from_env().work_dir
    try:
        age = time.time() - (work / "heartbeat").stat().st_mtime
    except FileNotFoundError:
        return 1
    return 0 if age <= HEALTH_MAX_AGE_S else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Dauerbetrieb")
    sub.add_parser("once", help="ein Durchlauf")
    sub.add_parser("migrate", help="nur Migrationen einspielen")
    sub.add_parser("health", help="Healthcheck")
    rb = sub.add_parser("rebuild", help="Archiv neu einlesen")
    rb.add_argument("--from", dest="start", type=_date, required=True)
    rb.add_argument("--to", dest="end", type=_date, required=True)
    args = parser.parse_args(argv)

    if args.cmd == "health":
        return _health()

    setup_logging()
    cfg = Config.from_env()
    _migrate(cfg)
    if args.cmd == "migrate":
        return 0
    if args.cmd == "once":
        run_once(cfg)
        return 0
    if args.cmd == "rebuild":
        results = rebuild(cfg, args.start, args.end)
        log.info("rebuild beendet", extra={"files": len(results)})
        return 0 if all(r.status == "ingested" for r in results) else 1

    log.info("ingest gestartet", extra={"version": __version__, "interval_s": cfg.interval_s})
    while True:
        try:
            results = run_once(cfg)
            if results:
                log.info("Durchlauf beendet", extra={"files": len(results)})
        except Exception:
            log.exception("Durchlauf fehlgeschlagen")
        time.sleep(cfg.interval_s)


if __name__ == "__main__":
    sys.exit(main())
