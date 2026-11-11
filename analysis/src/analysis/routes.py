"""Routenvergleich im Lauf: Rolle je Flug, Betriebsrichtung je Fenster, Bewertung je Flug.

Ablauf: Während der Flugbildung erhält jeder neue Flug mit Rolle eine vorläufige Zeile in
``flight_assessments`` (Bezugszeitpunkt und Stimme). Danach werden die Fenster neu berechnet,
in denen der Lauf Flüge gelöscht oder gebildet hat, und bewertet werden alle neuen Flüge sowie
alle Flüge in Fenstern, deren Betriebsrichtung sich geändert hat.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from analysis import db
from analysis.assign import Reference, assign
from analysis.config import Config
from analysis.deviation import approach, corridor, review, samples, section
from analysis.direction import WINDOW, decide, flight_heading, vote, window_start
from analysis.geo import XY, Local
from analysis.role import determine_role
from analysis.segment import Point

log = logging.getLogger("analysis")

_WINDOW_SQL = "to_timestamp(floor(extract(epoch FROM a.ref_ts) / 1800) * 1800)"


@dataclass(frozen=True)
class RouteContext:
    local: Local
    references: list[Reference]
    runway_headings: list[float]
    zones: list[tuple[int, XY]]  # (geofence_id, Referenzpunkt)


def enabled(cfg: Config) -> bool:
    return cfg.procedures_file is not None and cfg.procedures_file.is_file()


def load_context(conn: psycopg.Connection, cfg: Config) -> RouteContext:
    local = Local(cfg.ber_lat, cfg.ber_lon)
    references = [
        Reference(
            pid,
            name,
            kind,
            direction,
            sector,
            [local.xy(lat, lon) for lon, lat in geojson["coordinates"]],
            valid_from,
            valid_to,
        )
        for pid, name, kind, direction, sector, valid_from, valid_to, geojson in conn.execute(
            "SELECT id, name, kind, direction, sector, valid_from, valid_to,"
            " ST_AsGeoJSON(geom)::json FROM procedures WHERE superseded_at IS NULL ORDER BY id"
        )
    ]
    headings = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT runway_heading_deg FROM procedures WHERE superseded_at IS NULL"
        )
    ]
    zones = [
        (gid, local.xy(lat, lon))
        for gid, lat, lon in conn.execute(
            "SELECT id, ST_Y(ref_point), ST_X(ref_point) FROM geofences"
            " WHERE valid_to IS NULL ORDER BY id"
        )
    ]
    return RouteContext(local, references, headings, zones)


def record_role(
    conn: psycopg.Connection,
    run_id: int,
    flight_id: int,
    points: list[Point],
    ctx: RouteContext,
    cfg: Config,
) -> bool:
    """Legt für einen neuen Flug mit Rolle die vorläufige Bewertungszeile an."""
    role = determine_role(
        points,
        ctx.local,
        ber_radius_m=cfg.ber_radius_m,
        near_m=cfg.role_near_m,
        max_alt_ft=cfg.role_max_alt_ft,
        vrate_fpm=cfg.vrate_fpm,
    )
    if role is None:
        return False
    heading = flight_heading(role, near_m=cfg.role_near_m, dist_m=cfg.direction_dist_m)
    conn.execute(
        "INSERT INTO flight_assessments (flight_id, run_id, role, ref_ts, ref_heading_deg, vote,"
        " flight_sector, confidence, basis) VALUES (%s, %s, %s, %s, %s, %s, %s, 'none',"
        " 'noch nicht bewertet')",
        (
            flight_id,
            run_id,
            role.role,
            role.ref_ts,
            heading,
            vote(heading, ctx.runway_headings, tol_deg=cfg.direction_tol_deg),
            role.sector,
        ),
    )
    return True


def affected_windows(spans: list[tuple[datetime, datetime]]) -> set[datetime]:
    out: set[datetime] = set()
    for first, last in spans:
        w = window_start(first)
        while w <= last:
            out.add(w)
            w += WINDOW
    return out


def update_directions(
    conn: psycopg.Connection, run_id: int, windows: set[datetime], cfg: Config
) -> list[datetime]:
    """Berechnet die Betriebsrichtung der Fenster neu; liefert die Fenster, deren Richtung
    sich geändert hat."""
    if not windows:
        return []
    votes: dict[datetime, list[str]] = defaultdict(list)
    seen: set[datetime] = set()
    for ts, v in conn.execute(
        "SELECT ref_ts, vote FROM flight_assessments WHERE ref_ts >= %s AND ref_ts < %s",
        (min(windows), max(windows) + WINDOW),
    ):
        w = window_start(ts)
        if w in windows:
            seen.add(w)
            if v is not None:
                votes[w].append(v)
    keys = sorted(windows)
    old = dict(
        conn.execute(
            "DELETE FROM operating_directions WHERE window_start = ANY(%s)"
            " RETURNING window_start, direction",
            (keys,),
        ).fetchall()
    )
    changed = []
    for w in sorted(seen):
        d = decide(
            votes[w], min_flights=cfg.direction_min_flights, min_share=cfg.direction_min_share
        )
        conn.execute(
            "INSERT INTO operating_directions (window_start, direction, n_flights, share,"
            " basis, run_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (w, d.direction, d.n_flights, d.share, d.basis, run_id),
        )
        if old.get(w) != d.direction:
            changed.append(w)
    return changed


def flight_points(conn: psycopg.Connection, flight_id: int) -> list[Point]:
    """Spurpunkte eines gespeicherten Flugs mit Höhe aus ``positions``."""
    alts = {
        ts: (alt, rate)
        for ts, alt, rate in conn.execute(
            "SELECT p.ts, p.alt_baro_ft, p.baro_rate_fpm FROM positions p"
            " JOIN flights f ON p.icao24 = f.icao24 AND p.ts BETWEEN f.first_ts AND f.last_ts"
            " WHERE f.id = %s",
            (flight_id,),
        )
    }
    out = []
    for ts, lat, lon in conn.execute(
        "SELECT to_timestamp(ST_M(d.geom)), ST_Y(d.geom), ST_X(d.geom)"
        " FROM flights f, LATERAL ST_DumpPoints(f.track) d WHERE f.id = %s ORDER BY d.path",
        (flight_id,),
    ):
        alt, rate = alts.get(ts, (None, None))
        out.append(Point(ts, lat, lon, alt, rate, None, False))
    return out


def assess(
    conn: psycopg.Connection, run_id: int, flight_id: int, ctx: RouteContext, cfg: Config
) -> None:
    role, sector, direction = conn.execute(
        f"SELECT a.role, a.flight_sector, coalesce(o.direction, 'unknown')"
        f" FROM flight_assessments a"
        f" LEFT JOIN operating_directions o ON o.window_start = {_WINDOW_SQL}"
        f" WHERE a.flight_id = %s",
        (flight_id,),
    ).fetchone()
    points = flight_points(conn, flight_id)
    day = points[0].ts.astimezone(UTC).date()
    track = samples(points, ctx.local)
    a = assign(
        role,
        direction,
        sector,
        track,
        [r for r in ctx.references if r.valid_on(day)],
        max_alt_ft=cfg.route_max_alt_ft,
        ratio=cfg.assign_ratio,
    )
    row = {
        "flight_id": flight_id,
        "run_id": run_id,
        "direction": direction,
        "procedure_id": None if a.reference is None else a.reference.id,
        "confidence": a.confidence,
        "basis": a.basis,
        "mean_dev_m": a.mean_dev_m,
        "second_mean_dev_m": a.second_mean_dev_m,
        "eval_from": None,
        "eval_to": None,
        "max_dev_m": None,
        "outside_s": None,
        "outside_m": None,
        "deviation": False,
        "ref_geofence_id": None,
        "min_dist_ref_m": None,
        "proc_dist_ref_m": None,
        "approach": False,
        "review": False,
        "review_reasons": [],
        "in_reception_gap": None,
        "max_position_gap_s": None,
    }
    if a.confidence in ("high", "medium"):
        sec = section(track, a.reference.line, cfg.route_max_alt_ft)
        c = corridor(sec, half_width_m=cfg.corridor_m, min_s=cfg.corridor_min_s)
        b = approach([s.xy for s, _ in sec], a.reference.line, ctx.zones, tol_m=cfg.approach_tol)
        gap = db.in_reception_gap(conn, c.eval_from, c.eval_to)
        relevant = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM overflight_events WHERE flight_id = %s AND relevant)",
            (flight_id,),
        ).fetchone()[0]
        flagged, reasons = review(
            deviation=c.deviation,
            approach=b.approach,
            confidence=a.confidence,
            in_reception_gap=gap,
            max_position_gap_s=c.max_position_gap_s,
            max_gap_s=cfg.review_max_gap_s,
            relevant_event=relevant,
        )
        row |= {
            "eval_from": c.eval_from,
            "eval_to": c.eval_to,
            "max_dev_m": c.max_dev_m,
            "outside_s": c.outside_s,
            "outside_m": c.outside_m,
            "deviation": c.deviation,
            "ref_geofence_id": b.geofence_id,
            "min_dist_ref_m": b.min_dist_ref_m,
            "proc_dist_ref_m": b.proc_dist_ref_m,
            "approach": b.approach,
            "review": flagged,
            "review_reasons": reasons,
            "in_reception_gap": gap,
            "max_position_gap_s": c.max_position_gap_s,
        }
    sets = ", ".join(f"{k} = %({k})s" for k in row if k != "flight_id")
    conn.execute(f"UPDATE flight_assessments SET {sets} WHERE flight_id = %(flight_id)s", row)


def pending(conn: psycopg.Connection, run_id: int, changed: list[datetime]) -> list[int]:
    """Neue Flüge dieses Laufs, Flüge in Fenstern mit geänderter Betriebsrichtung und Flüge,
    deren Bewertung noch fehlt (``assess`` setzt ``direction`` immer)."""
    return [
        r[0]
        for r in conn.execute(
            f"SELECT a.flight_id FROM flight_assessments a"
            f" WHERE a.run_id = %s OR {_WINDOW_SQL} = ANY(%s) OR a.direction IS NULL"
            f" ORDER BY a.flight_id",
            (run_id, changed),
        )
    ]


def run_step(
    conn: psycopg.Connection,
    cfg: Config,
    run_id: int,
    ctx: RouteContext,
    spans: list[tuple[datetime, datetime]],
    counts: db.Counts,
) -> None:
    changed = update_directions(conn, run_id, affected_windows(spans), cfg)
    for flight_id in pending(conn, run_id, changed):
        try:
            with conn.transaction():
                assess(conn, run_id, flight_id, ctx, cfg)
        except psycopg.OperationalError:
            raise
        except Exception as e:
            counts.skipped += 1
            log.warning(
                "Bewertung übersprungen",
                extra={"flight_id": flight_id, "error": str(e)},
                exc_info=True,
            )
            continue
        counts.assessments += 1
