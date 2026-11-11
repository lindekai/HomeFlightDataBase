"""Zuordnung Flug → Verfahren mit Sicherheitsstufe und Begründung (ohne Datenbank)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import fmean

from analysis.deviation import Sample, section
from analysis.events import SECTORS
from analysis.geo import XY

KIND_FOR_ROLE = {"departure": "SID", "arrival": "STAR"}
_LEVELS = ("high", "medium", "low")


@dataclass(frozen=True)
class Reference:
    """Gültige Fassung eines Verfahrens, Ideallinie in der lokalen Ebene."""

    id: int
    name: str
    kind: str
    direction: str
    sector: str
    line: list[XY]
    valid_from: date
    valid_to: date | None

    def valid_on(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day < self.valid_to)


@dataclass(frozen=True)
class Assignment:
    reference: Reference | None
    confidence: str  # high | medium | low | none
    basis: str
    mean_dev_m: float | None
    second_mean_dev_m: float | None


def sector_fit(flight: str, procedure: str) -> str | None:
    """``genau`` bei gleichem Sektor, ``ungefähr`` beim Nachbarsektor, sonst ``None``."""
    if flight == procedure:
        return "genau"
    step = (SECTORS.index(flight) - SECTORS.index(procedure)) % len(SECTORS)
    return "ungefähr" if step in (1, len(SECTORS) - 1) else None


def assign(
    role: str,
    direction: str,
    flight_sector: str,
    track: list[Sample],
    references: list[Reference],
    *,
    max_alt_ft: int | None,
    ratio: float,
) -> Assignment:
    kind = KIND_FOR_ROLE[role]
    sentences = [
        f"Betriebsrichtung {direction}."
        if direction != "unknown"
        else "Betriebsrichtung unbekannt, Verfahren beider Richtungen geprüft."
    ]
    scored: list[tuple[float, Reference, str]] = []
    for ref in references:
        if ref.kind != kind or (direction != "unknown" and ref.direction != direction):
            continue
        fit = sector_fit(flight_sector, ref.sector)
        if fit is None:
            continue
        sec = section(track, ref.line, max_alt_ft)
        if len(sec) < 2:
            continue
        scored.append((fmean(d for _, d in sec), ref, fit))
    if not scored:
        sentences.append(
            f"Kein {kind} passt nach Richtung, Sektor {flight_sector} und Geltungsabschnitt."
        )
        return Assignment(None, "none", " ".join(sentences), None, None)

    scored.sort(key=lambda s: s[0])
    best, ref, fit = scored[0]
    second = scored[1] if len(scored) > 1 else None
    sentences.append(f"Sektor {flight_sector}, Verfahren {ref.name} {ref.sector}: passt {fit}.")
    if second is None:
        sentences.append(f"Mittlere Abweichung {best:.0f} m, kein weiteres Verfahren in Frage.")
        distinct = True
    else:
        distinct = second[0] >= ratio * best
        sentences.append(
            f"Mittlere Abweichung {best:.0f} m, nächstes Verfahren {second[1].name}"
            f" {second[0]:.0f} m ({'deutlich' if distinct else 'nicht deutlich'} getrennt)."
        )
    failed = (direction == "unknown") + (fit != "genau") + (not distinct)
    return Assignment(
        ref,
        _LEVELS[min(failed, 2)],
        " ".join(sentences),
        best,
        None if second is None else second[0],
    )
