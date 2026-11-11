"""Abweichung vom Korridor (C), Annäherung an Zonen (B) und Prüffall (E), ohne Datenbank."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from analysis.geo import XY, Local, distance_to_line, project
from analysis.segment import Point

CONFIDENCE_LABEL = {"high": "hoch", "medium": "mittel", "low": "niedrig", "none": "keine"}


@dataclass(frozen=True)
class Sample:
    ts: datetime
    xy: XY
    alt_ft: int | None


def samples(points: list[Point], local: Local) -> list[Sample]:
    return [Sample(p.ts, local.xy(p.lat, p.lon), p.alt_ft) for p in points]


def section(
    track: list[Sample], line: list[XY], max_alt_ft: int | None
) -> list[tuple[Sample, float]]:
    """Geltungsabschnitt: Positionen, deren Lotfußpunkt zwischen Anfang und Ende der Linie
    liegt (bei gesetzter Höhengrenze nur bis zu dieser Höhe), mit seitlichem Abstand."""
    out = []
    for s in track:
        if max_alt_ft is not None and (s.alt_ft is None or s.alt_ft > max_alt_ft):
            continue
        pr = project(s.xy, line)
        if pr.within:
            out.append((s, pr.dist_m))
    return out


@dataclass(frozen=True)
class Corridor:
    eval_from: datetime
    eval_to: datetime
    max_dev_m: float
    outside_s: float
    outside_m: float
    deviation: bool
    max_position_gap_s: float


def corridor(sec: list[tuple[Sample, float]], *, half_width_m: float, min_s: float) -> Corridor:
    """Außerhalb-Abschnitte aus aufeinanderfolgenden Positionen; Ein- und Austritt linear
    zwischen zwei Positionen interpoliert. Voraussetzung: mindestens zwei Positionen."""
    w = half_width_m
    spans: list[list] = []  # [Beginn, Ende, Strecke m]
    first, d_first = sec[0]
    if d_first > w:
        spans.append([first.ts, first.ts, 0.0])
    gaps = []
    for (a, da), (b, db) in zip(sec, sec[1:], strict=False):
        dt = (b.ts - a.ts).total_seconds()
        gaps.append(dt)
        seg = math.dist(a.xy, b.xy)
        if da > w and db > w:
            spans[-1][1] = b.ts
            spans[-1][2] += seg
        elif da <= w < db:
            f = (w - da) / (db - da)
            spans.append([a.ts + timedelta(seconds=f * dt), b.ts, seg * (1 - f)])
        elif db <= w < da:
            f = (da - w) / (da - db)
            spans[-1][1] = a.ts + timedelta(seconds=f * dt)
            spans[-1][2] += seg * f
    durations = [(end - start).total_seconds() for start, end, _ in spans]
    return Corridor(
        eval_from=first.ts,
        eval_to=sec[-1][0].ts,
        max_dev_m=max(d for _, d in sec),
        outside_s=sum(durations),
        outside_m=sum(m for _, _, m in spans),
        deviation=any(d >= min_s for d in durations),
        max_position_gap_s=max(gaps),
    )


@dataclass(frozen=True)
class Approach:
    geofence_id: int | None
    min_dist_ref_m: float | None
    proc_dist_ref_m: float | None
    approach: bool


def approach(
    track: list[XY], line: list[XY], zones: list[tuple[int, XY]], *, tol_m: float
) -> Approach:
    """Für jede Zone kleinster Abstand von Spur und Ideallinie zum Referenzpunkt; maßgeblich
    ist die Zone mit der kleinsten Differenz Spur − Ideallinie."""
    best: Approach | None = None
    for gid, ref in zones:
        flight = distance_to_line(ref, track)
        ideal = distance_to_line(ref, line)
        if best is None or flight - ideal < best.min_dist_ref_m - best.proc_dist_ref_m:
            best = Approach(gid, flight, ideal, flight - ideal < -tol_m)
    return best or Approach(None, None, None, False)


def review(
    *,
    deviation: bool,
    approach: bool,
    confidence: str,
    in_reception_gap: bool | None,
    max_position_gap_s: float | None,
    max_gap_s: float,
    relevant_event: bool,
) -> tuple[bool, list[str]]:
    """Prüffall, wenn alle Bedingungen gelten; liefert zusätzlich die erfüllten Bedingungen."""
    trigger = deviation or approach
    rated = confidence in ("high", "medium")
    quality = (
        in_reception_gap is False
        and max_position_gap_s is not None
        and max_position_gap_s <= max_gap_s
    )
    reasons = []
    if deviation:
        reasons.append("Abweichung")
    if approach:
        reasons.append("Annäherung")
    if rated:
        reasons.append(f"Sicherheit {CONFIDENCE_LABEL[confidence]}")
    if quality:
        reasons.append("Datenqualität ausreichend")
    if relevant_event:
        reasons.append("relevanter Überflug")
    return trigger and rated and quality and relevant_event, reasons
