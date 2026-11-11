"""Flugverfahren (SID/STAR): YAML lesen und prüfen, Geometrie, Abgleich mit ``procedures``.

Die Datei wird als Ganzes geprüft; bei einem Fehler wird nichts geladen und die bisherige
Fassung bleibt aktiv. Fehlermeldungen nennen Eintrag und Feld, nie Koordinaten.
Geänderte Verfahren (gleicher Name, gleicher Gültigkeitsbeginn) erhalten eine neue Fassung;
die alte wird mit ``superseded_at`` geschlossen.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import psycopg
import yaml
from psycopg.types.json import Jsonb

from analysis.events import sector
from analysis.geo import XY, Local, azimuth_deg, exit_point, length
from analysis.segment import haversine_m

KINDS = ("SID", "STAR")
MAX_WAYPOINT_DIST_M = 200_000
_RUNWAY = re.compile(r"^(0[1-9]|[12]\d|3[0-6])([LCR]?)$")
_DMS = re.compile(
    r"^\s*(\d{2})\s*(\d{2})\s*(\d{2}(?:\.\d+)?)\s*([NS])"
    r"\s*(\d{3})\s*(\d{2})\s*(\d{2}(?:\.\d+)?)\s*([EW])\s*$"
)


class ProcedureError(ValueError):
    pass


@dataclass(frozen=True)
class Procedure:
    name: str
    kind: str  # SID | STAR
    runway: str
    runway_heading_deg: float  # Kurs Schwelle → Gegenschwelle
    direction: str  # west | east
    sector: str
    airac: str | None
    valid_from: date
    valid_to: date | None
    source: str | None
    waypoints: tuple[str, ...]
    line: tuple[tuple[float, float], ...]  # (lat, lon); SID ab der Gegenschwelle
    constraints: dict = field(default_factory=dict)
    length_m: float = 0.0

    def content_hash(self) -> str:
        data = json.dumps(asdict(self), sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class ProcedureSync:
    changed: list[str]
    removed: list[str]


class _Loader(yaml.SafeLoader):
    """SafeLoader, der doppelte Schlüssel ablehnt statt den letzten zu übernehmen."""


def _mapping(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ProcedureError(f"Zeile {key_node.start_mark.line + 1}: Name {key!r} doppelt")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def direction_class(heading_deg: float) -> str:
    """Betriebsrichtung zu einem Kurs: 180–359° ``west``, 0–179° ``east``."""
    return "west" if 180 <= heading_deg % 360 < 360 else "east"


def opposite_runway(runway: str) -> str:
    m = _RUNWAY.match(runway)
    number = (int(m.group(1)) + 17) % 36 + 1
    return f"{number:02d}" + {"L": "R", "R": "L", "C": "C", "": ""}[m.group(2)]


def parse_coord(value, what: str) -> tuple[float, float]:
    """``"GG MM SS.ssN GGG MM SS.ssE"`` oder ``[lat, lon]`` → (lat, lon)."""
    if isinstance(value, str):
        m = _DMS.match(value)
        if not m:
            raise ProcedureError(f"{what}: Koordinate unlesbar")
        d1, m1, s1, ns, d2, m2, s2, ew = m.groups()
        if int(m1) >= 60 or float(s1) >= 60 or int(m2) >= 60 or float(s2) >= 60:
            raise ProcedureError(f"{what}: Koordinate unlesbar")
        lat = (int(d1) + int(m1) / 60 + float(s1) / 3600) * (1 if ns == "N" else -1)
        lon = (int(d2) + int(m2) / 60 + float(s2) / 3600) * (1 if ew == "E" else -1)
    elif (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        lat, lon = float(value[0]), float(value[1])
    else:
        raise ProcedureError(f"{what}: Koordinate unlesbar")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ProcedureError(f"{what}: Koordinate außerhalb ±90/±180")
    return lat, lon


def _date(value, what: str, required: bool) -> date | None:
    if value is None and not required:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ProcedureError(f"{what}: Datum JJJJ-MM-TT erwartet")


def _overlap(a: Procedure, b: Procedure) -> bool:
    return a.valid_from < (b.valid_to or date.max) and b.valid_from < (a.valid_to or date.max)


def _sector(line: list[XY], kind: str, radius: float) -> str:
    """Richtung vom Referenzpunkt zum Punkt, an dem die Linie den Radius verlässt (SID) bzw.
    betritt (STAR); liegt sie ganz innerhalb, der letzte bzw. erste Punkt."""
    outward = line if kind == "SID" else line[::-1]
    point = exit_point(outward, radius) or outward[-1]
    return sector(azimuth_deg((0.0, 0.0), point))


def parse_procedures(
    data, *, ber_lat: float, ber_lon: float, ber_radius_m: float
) -> list[Procedure]:
    if not isinstance(data, dict):
        raise ProcedureError("Datei: Objekt mit waypoints, runways und procedures erwartet")
    source = data.get("source")
    source = None if source is None else str(source)
    for key, kind in (("waypoints", dict), ("runways", dict), ("procedures", list)):
        if not isinstance(data.get(key), kind) or not data[key]:
            raise ProcedureError(f"Datei, Feld {key}: fehlt oder leer")

    waypoints: dict[str, tuple[float, float]] = {}
    for name, value in data["waypoints"].items():
        if not isinstance(name, str) or not name.strip():
            raise ProcedureError(f"Wegpunkt {name!r}: Name muss Text sein")
        lat, lon = parse_coord(value, f"Wegpunkt {name}, Feld Koordinate")
        if haversine_m(lat, lon, ber_lat, ber_lon) > MAX_WAYPOINT_DIST_M:
            raise ProcedureError(
                f"Wegpunkt {name}, Feld Koordinate: weiter als 200 km vom Referenzpunkt"
            )
        waypoints[name] = (lat, lon)

    runways: dict[str, tuple[float, float]] = {}
    for name, value in data["runways"].items():
        if not isinstance(name, str) or not _RUNWAY.match(name):
            raise ProcedureError(f'Startbahn {name!r}: Bezeichnung wie "25R" erwartet')
        runways[name] = parse_coord(value, f"Startbahn {name}, Feld Schwelle")

    local = Local(ber_lat, ber_lon)
    procedures: list[Procedure] = []
    for i, p in enumerate(data["procedures"]):
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"]:
            raise ProcedureError(f"Verfahren Nr. {i + 1}, Feld name: fehlt")
        name = p["name"]
        what = f"Verfahren {name}"
        kind = p.get("kind")
        if kind not in KINDS:
            raise ProcedureError(f"{what}, Feld kind: SID oder STAR erwartet")
        runway = p.get("runway")
        if not isinstance(runway, str) or runway not in runways:
            raise ProcedureError(f"{what}, Feld runway: Startbahn {runway!r} unbekannt")
        opposite = opposite_runway(runway)
        if opposite not in runways:
            raise ProcedureError(f"{what}, Feld runway: Gegenschwelle {opposite} unbekannt")
        valid_from = _date(p.get("valid_from"), f"{what}, Feld valid_from", required=True)
        valid_to = _date(p.get("valid_to"), f"{what}, Feld valid_to", required=False)
        if valid_to is not None and valid_to < valid_from:
            raise ProcedureError(f"{what}, Feld valid_to: liegt vor valid_from")
        route = p.get("route")
        if not isinstance(route, list) or len(route) < (1 if kind == "SID" else 2):
            minimum = "einen Wegpunkt" if kind == "SID" else "zwei Wegpunkte"
            raise ProcedureError(f"{what}, Feld route: mindestens {minimum} erwartet")
        for wp in route:
            if not isinstance(wp, str) or wp not in waypoints:
                raise ProcedureError(f"{what}, Feld route: Wegpunkt {wp!r} unbekannt")
        constraints = p.get("constraints") or {}
        if not isinstance(constraints, dict):
            raise ProcedureError(f"{what}, Feld constraints: Zuordnung je Wegpunkt erwartet")
        airac = p.get("airac")

        line = [waypoints[wp] for wp in route]
        if kind == "SID":
            line.insert(0, runways[opposite])
        line_xy = [local.xy(*c) for c in line]
        heading = azimuth_deg(local.xy(*runways[runway]), local.xy(*runways[opposite]))
        proc = Procedure(
            name=name,
            kind=kind,
            runway=runway,
            runway_heading_deg=round(heading, 1),
            direction=direction_class(heading),
            sector=_sector(line_xy, kind, ber_radius_m),
            airac=None if airac is None else str(airac),
            valid_from=valid_from,
            valid_to=valid_to,
            source=source,
            waypoints=tuple(route),
            line=tuple(line),
            constraints=constraints,
            length_m=round(length(line_xy)),
        )
        for other in procedures:
            if other.name == name and _overlap(other, proc):
                raise ProcedureError(f"{what}, Feld name: doppelt bei überlappender Gültigkeit")
        procedures.append(proc)
    return procedures


def read_procedures(
    path: Path, *, ber_lat: float, ber_lon: float, ber_radius_m: float
) -> list[Procedure]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ProcedureError(f"{path.name}: nicht lesbar ({e.strerror})") from e
    try:
        data = yaml.load(text, Loader=_Loader)
    except yaml.MarkedYAMLError as e:
        # Nur die Zeile nennen: die Meldung von PyYAML zitiert sonst den Inhalt.
        line = e.problem_mark.line + 1 if e.problem_mark else "?"
        raise ProcedureError(f"{path.name}: kein gültiges YAML (Zeile {line})") from None
    except yaml.YAMLError:
        raise ProcedureError(f"{path.name}: kein gültiges YAML") from None
    return parse_procedures(data, ber_lat=ber_lat, ber_lon=ber_lon, ber_radius_m=ber_radius_m)


_CURRENT = """
SELECT id, content_hash FROM procedures
WHERE name = %(name)s AND valid_from = %(valid_from)s AND superseded_at IS NULL
"""

_INSERT = """
INSERT INTO procedures (name, kind, runway, runway_heading_deg, direction, sector, airac,
  valid_from, valid_to, source, geom, waypoints, constraints, content_hash)
VALUES (%(name)s, %(kind)s, %(runway)s, %(runway_heading_deg)s, %(direction)s, %(sector)s,
  %(airac)s, %(valid_from)s, %(valid_to)s, %(source)s, ST_GeomFromEWKT(%(ewkt)s),
  %(waypoints)s, %(constraints)s, %(content_hash)s)
"""


def load_procedures(conn: psycopg.Connection, procedures: list[Procedure]) -> ProcedureSync:
    """Gleicht alle Verfahren in einer Transaktion ab; fehlende Verfahren werden geschlossen."""
    changed: list[str] = []
    with conn.transaction():
        for p in procedures:
            content_hash = p.content_hash()
            params = {
                "name": p.name,
                "kind": p.kind,
                "runway": p.runway,
                "runway_heading_deg": p.runway_heading_deg,
                "direction": p.direction,
                "sector": p.sector,
                "airac": p.airac,
                "valid_from": p.valid_from,
                "valid_to": p.valid_to,
                "source": p.source,
                "ewkt": "SRID=4326;LINESTRING("
                + ", ".join(f"{lon} {lat}" for lat, lon in p.line)
                + ")",
                "waypoints": Jsonb(list(p.waypoints)),
                "constraints": Jsonb(p.constraints),
                "content_hash": content_hash,
            }
            current = conn.execute(_CURRENT, params).fetchone()
            if current and current[1] == content_hash:
                continue
            if current:
                conn.execute(
                    "UPDATE procedures SET superseded_at = now() WHERE id = %s", (current[0],)
                )
            conn.execute(_INSERT, params)
            changed.append(p.name)
        keep = [(p.name, p.valid_from) for p in procedures]
        removed = conn.execute(
            "UPDATE procedures SET superseded_at = now()"
            " WHERE superseded_at IS NULL AND NOT ((name, valid_from) IN"
            " (SELECT * FROM unnest(%s::text[], %s::date[])))"
            " RETURNING name",
            ([k[0] for k in keep], [k[1] for k in keep]),
        ).fetchall()
    return ProcedureSync(changed, sorted(r[0] for r in removed))
