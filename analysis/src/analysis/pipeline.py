"""Laufsteuerung: Zeitfenster bestimmen, Flüge und Überflüge neu bilden, protokollieren."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

from analysis import __version__, db, events, routes
from analysis.config import Config
from analysis.procedures import ProcedureSync, load_procedures, read_procedures
from analysis.segment import Point, segment
from analysis.zones import ZoneSync, load_zones, read_zones

log = logging.getLogger("analysis")


class SchemaMissing(RuntimeError):
    pass


class NoZones(RuntimeError):
    pass


@dataclass(frozen=True)
class RunResult:
    run_id: int
    kind: str
    window_from: datetime
    window_to: datetime
    flights: int
    events: int
    skipped: int
    assessments: int = 0


def compute_window(conn: psycopg.Connection, cfg: Config) -> tuple[datetime, datetime] | None:
    end = db.data_end(conn)
    if end is None:
        return None
    settle = timedelta(seconds=cfg.settle_s)
    window_to = end - settle
    pending = db.pending_files(conn)
    if pending:
        first = min(pending, key=lambda f: f.start)
        if first.start - settle < window_to:
            window_to = first.start - settle
            # Bleibt eine Datei dauerhaft uneingelesen (z. B. ``failed``), steht die Auswertung.
            log.warning(
                "noch nicht eingelesene Datei begrenzt das Auswertungsfenster",
                extra={
                    "path": first.path,
                    "status": first.status,
                    "file_start": first.start,
                    "waiting_s": round(first.waiting_s),
                },
            )

    last = db.last_incremental(conn)
    if last is None:
        window_from = db.first_position_ts(conn)
        if window_from is None:
            return None
    else:
        window_from, last_started = last
        late = db.late_start(conn, last_started, window_from)
        if late is not None:
            window_from = min(window_from, late - settle)
    if window_to <= window_from:
        return None
    return window_from, window_to


def watermark_lag_s(conn: psycopg.Connection) -> float | None:
    """Abstand zwischen Ende der eingelesenen Daten und dem Wasserzeichen in Sekunden.

    Ohne eingelesene Daten ``None``; ohne erfolgreichen Lauf zählt der Datenbeginn als
    Wasserzeichen. Ein abgeschalteter Empfänger erhöht den Wert nicht."""
    end = db.data_end(conn)
    if end is None:
        return None
    last = db.last_incremental(conn)
    mark = last[0] if last is not None else db.first_data_start(conn)
    return max(0.0, (end - mark).total_seconds())


def _aircraft(
    conn: psycopg.Connection,
    cfg: Config,
    run_id: int,
    icao: str,
    points: list[Point],
    zones: dict[int, int],
    ctx: routes.RouteContext | None,
) -> tuple[int, int, list[tuple[datetime, datetime]]]:
    n_flights = n_events = 0
    spans = []
    for seg in segment(icao, points, gap_s=cfg.flight_gap_s, max_speed_kt=cfg.max_speed_kt):
        flight_id = db.insert_flight(conn, run_id, seg)
        n_flights += 1
        spans.append((seg.first_ts, seg.last_ts))
        for c in events.crossings(conn, flight_id):
            event = events.build_event(c, seg.points, zones[c.geofence_id], cfg)
            event["in_reception_gap"] = db.in_reception_gap(conn, c.entry, c.exit)
            db.insert_event(conn, run_id, flight_id, event)
            n_events += 1
        if ctx is not None:
            routes.record_role(conn, run_id, flight_id, seg.points, ctx, cfg)
    return n_flights, n_events, spans


def _process(
    conn: psycopg.Connection,
    cfg: Config,
    run_id: int,
    start: datetime,
    end: datetime,
    deleted: dict[str, tuple[datetime, datetime]],
) -> db.Counts:
    zones = db.current_zones(conn)
    if not zones:
        raise NoZones("keine aktuelle Zone in geofences – Zonendatei laden")
    if routes.enabled(cfg):
        ctx = routes.load_context(conn, cfg)
    else:
        ctx = None
        log.warning(
            "keine Verfahrensdatei – Routenvergleich übersprungen",
            extra={"file": None if cfg.procedures_file is None else str(cfg.procedures_file)},
        )
    # Gelöschte Flüge werden ab ihrem Beginn neu gebildet, aber nur für ihr Flugzeug.
    ranges = {icao: (min(start, first), max(end, last)) for icao, (first, last) in deleted.items()}
    counts = db.Counts()
    spans = list(deleted.values())
    for icao, points in db.aircraft_points(conn, start, end, ranges):
        try:
            with conn.transaction():
                n_flights, n_events, new = _aircraft(conn, cfg, run_id, icao, points, zones, ctx)
        except psycopg.OperationalError:
            raise
        except Exception as e:
            counts.skipped += 1
            log.warning(
                "Flugzeug übersprungen", extra={"icao24": icao, "error": str(e)}, exc_info=True
            )
            continue
        counts.flights += n_flights
        counts.events += n_events
        spans += new
    if ctx is not None:
        routes.run_step(conn, cfg, run_id, ctx, spans, counts)
    return counts


def _run(
    conn: psycopg.Connection, cfg: Config, kind: str, start: datetime, end: datetime
) -> RunResult:
    gap = timedelta(seconds=cfg.flight_gap_s)
    run_id = db.start_run(conn, kind, __version__, cfg.params(), start, end)
    try:
        with conn.transaction():
            if kind == "incremental":
                deleted = db.delete_flights(conn, last_from=start - gap)
            else:
                deleted = db.delete_flights(conn, last_from=start - gap, first_to=end + gap)
            counts = _process(conn, cfg, run_id, start, end, deleted)
            db.finish_run(conn, run_id, "ok", counts)
    except Exception as e:
        try:
            db.finish_run(conn, run_id, "failed", db.Counts(), str(e))
        except psycopg.Error:
            log.exception("Fehlerstatus nicht gespeichert")
        raise
    return RunResult(
        run_id,
        kind,
        start,
        end,
        counts.flights,
        counts.events,
        counts.skipped,
        counts.assessments,
    )


def _locked(cfg: Config, work):
    with psycopg.connect(cfg.db_dsn, autocommit=True) as conn:
        if not db.schema_ready(conn):
            raise SchemaMissing("Tabelle analysis_runs fehlt – ingest hat noch nicht migriert")
        if not db.try_lock(conn):
            log.info("anderer Lauf aktiv, übersprungen")
            return None
        try:
            return work(conn)
        finally:
            db.unlock(conn)


def run_once(cfg: Config) -> RunResult | None:
    def work(conn):
        window = compute_window(conn, cfg)
        return None if window is None else _run(conn, cfg, "incremental", *window)

    return _locked(cfg, work)


def rebuild(cfg: Config, start: datetime, end: datetime) -> RunResult | None:
    """Berechnet Flüge im Zeitraum neu, höchstens bis zum letzten inkrementellen Lauf."""

    def work(conn):
        last = db.last_incremental(conn)
        if last is None:
            return None
        to = min(end, last[0])
        return None if to <= start else _run(conn, cfg, "rebuild", start, to)

    return _locked(cfg, work)


def sync_zones(cfg: Config, path: Path) -> ZoneSync:
    zones = read_zones(path, cfg.default_relevance_ft)
    with psycopg.connect(cfg.db_dsn, autocommit=True) as conn:
        if not db.schema_ready(conn):
            raise SchemaMissing("Tabelle geofences fehlt – ingest hat noch nicht migriert")
        result = load_zones(conn, zones)
    if result.changed or result.removed:
        log.info(
            "Zonen geändert – ältere Zeiträume bei Bedarf mit 'analysis rebuild' neu berechnen",
            extra={"changed": result.changed, "removed": result.removed},
        )
    return result


def sync_procedures(cfg: Config, path: Path) -> ProcedureSync:
    procedures = read_procedures(
        path, ber_lat=cfg.ber_lat, ber_lon=cfg.ber_lon, ber_radius_m=cfg.ber_radius_m
    )
    with psycopg.connect(cfg.db_dsn, autocommit=True) as conn:
        if conn.execute("SELECT to_regclass('procedures')").fetchone()[0] is None:
            raise SchemaMissing("Tabelle procedures fehlt – ingest hat noch nicht migriert")
        result = load_procedures(conn, procedures)
    if result.changed or result.removed:
        log.info(
            "Verfahren geändert – ältere Zeiträume bei Bedarf mit 'analysis rebuild' neu"
            " berechnen",
            extra={"changed": result.changed, "removed": result.removed},
        )
    return result
