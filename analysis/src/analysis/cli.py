"""Kommandozeile: ``python -m analysis {run|once|rebuild|zones|procedures|health}``."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from analysis import __version__
from analysis.config import Config
from analysis.logjson import setup_logging
from analysis.pipeline import rebuild, run_once, sync_procedures, sync_zones, watermark_lag_s
from analysis.procedures import ProcedureError

log = logging.getLogger("analysis")


def _date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _health() -> int:
    cfg = Config.from_env()
    try:
        age = time.time() - cfg.heartbeat_file.stat().st_mtime
    except FileNotFoundError:
        return 1
    if age > 3 * cfg.interval_s:
        return 1
    try:
        with psycopg.connect(cfg.db_dsn, connect_timeout=5) as c:
            row = c.execute("SELECT status FROM analysis_runs ORDER BY id DESC LIMIT 1").fetchone()
            lag = watermark_lag_s(c)
    except psycopg.Error:
        return 1
    if row and row[0] == "failed":
        return 1
    # Wasserzeichen hängt hinter vorhandenen Daten zurück (z. B. dauerhaft defekte Datei).
    return 1 if lag is not None and lag > cfg.max_lag_s else 0


def _log_result(result) -> None:
    if result is not None:
        log.info(
            "Lauf beendet",
            extra={
                "kind": result.kind,
                "window_from": result.window_from,
                "window_to": result.window_to,
                "flights": result.flights,
                "events": result.events,
                "skipped": result.skipped,
                "assessments": result.assessments,
            },
        )


def _iteration(cfg: Config) -> None:
    if cfg.zones_file is not None:
        sync_zones(cfg, cfg.zones_file)
    if cfg.procedures_file is not None and cfg.procedures_file.is_file():
        try:
            sync_procedures(cfg, cfg.procedures_file)
        except ProcedureError as e:
            log.error(
                "Verfahrensdatei ungültig – bisherige Fassung bleibt aktiv",
                extra={"error": str(e)},
            )
        except Exception as e:
            # Unerwarteter Fehler: nur der Typ, denn Text und Traceback könnten den Dateiinhalt
            # zitieren. Flugbildung und Überflüge laufen trotzdem weiter.
            log.error(
                "Verfahrensdatei nicht verarbeitet – bisherige Fassung bleibt aktiv",
                extra={"error": type(e).__name__},
            )
    _log_result(run_once(cfg))
    cfg.heartbeat_file.touch()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analysis")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Dauerbetrieb")
    sub.add_parser("once", help="ein Lauf")
    sub.add_parser("health", help="Healthcheck")
    zp = sub.add_parser("zones", help="Zonendatei laden")
    zp.add_argument("file", nargs="?")
    pp = sub.add_parser("procedures", help="Verfahrensdatei laden")
    pp.add_argument("file", nargs="?")
    rb = sub.add_parser("rebuild", help="Zeitraum neu berechnen")
    rb.add_argument("--from", dest="start", type=_date, required=True)
    rb.add_argument("--to", dest="end", type=_date, required=True)
    args = parser.parse_args(argv)

    if args.cmd == "health":
        return _health()

    setup_logging()
    cfg = Config.from_env()
    if args.cmd == "zones":
        path = Path(args.file) if args.file else cfg.zones_file
        if path is None:
            log.error("keine Zonendatei angegeben (Argument oder ANALYSIS_ZONES_FILE)")
            return 2
        result = sync_zones(cfg, path)
        log.info("Zonen geladen", extra={"changed": result.changed, "removed": result.removed})
        return 0
    if args.cmd == "procedures":
        path = Path(args.file) if args.file else cfg.procedures_file
        if path is None:
            log.error("keine Verfahrensdatei angegeben (Argument oder ANALYSIS_PROCEDURES_FILE)")
            return 2
        try:
            result = sync_procedures(cfg, path)
        except ProcedureError as e:
            log.error("Verfahrensdatei ungültig", extra={"error": str(e)})
            return 1
        log.info("Verfahren geladen", extra={"changed": result.changed, "removed": result.removed})
        return 0
    if args.cmd == "once":
        _iteration(cfg)
        return 0
    if args.cmd == "rebuild":
        result = rebuild(cfg, args.start, args.end)
        _log_result(result)
        return 0 if result is not None else 1

    log.info("analysis gestartet", extra={"version": __version__, "interval_s": cfg.interval_s})
    while True:
        try:
            _iteration(cfg)
        except Exception:
            log.exception("Lauf fehlgeschlagen")
        time.sleep(cfg.interval_s)


if __name__ == "__main__":
    sys.exit(main())
