"""Einlesen einer Rohdatei und Normalisierung zu Positionen, Lücken und Metadaten."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


class InconsistentFile(ValueError):
    """Datei enthält widersprüchliche Kopfdaten (z. B. mehrere receiver_id)."""


@dataclass(frozen=True)
class Position:
    ts: datetime
    icao24: str
    callsign: str | None
    lon: float
    lat: float
    on_ground: bool
    alt_baro_ft: int | None
    alt_geom_ft: int | None
    gs_kt: float | None
    track_deg: float | None
    baro_rate_fpm: int | None
    squawk: str | None
    source_type: str | None
    nic: int | None
    nac_p: int | None
    sil: int | None
    rssi_dbfs: float | None


POSITION_FIELDS = tuple(Position.__dataclass_fields__)


@dataclass(frozen=True)
class Gap:
    start: datetime
    end: datetime
    reason: str


@dataclass
class AircraftSeen:
    icao24: str
    registration: str | None
    type_code: str | None
    first_seen: datetime
    last_seen: datetime


@dataclass
class ParsedFile:
    receiver_id: str | None = None
    synthetic: bool = False
    positions: list[Position] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    aircraft: dict[str, AircraftSeen] = field(default_factory=dict)
    period_start: datetime | None = None
    period_end: datetime | None = None
    clock_offset_max_s: float | None = None
    receiver_free_bytes: int | None = None
    bad_lines: int = 0


def _num(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _int(v) -> int | None:
    return int(v) if _num(v) else None


def _float(v) -> float | None:
    return float(v) if _num(v) else None


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def _positions(data: dict) -> Iterator[tuple[Position, dict]]:
    now = data["now"]
    for ac in data.get("aircraft", []):
        hex_, lat, lon, seen_pos = ac.get("hex"), ac.get("lat"), ac.get("lon"), ac.get("seen_pos")
        if not isinstance(hex_, str) or not (_num(lat) and _num(lon) and _num(seen_pos)):
            continue
        alt_baro = ac.get("alt_baro")
        on_ground = alt_baro == "ground"
        yield (
            Position(
                ts=datetime.fromtimestamp(round(now - seen_pos, 1), tz=UTC),
                icao24=hex_.lower(),
                callsign=(ac.get("flight") or "").strip() or None,
                lon=float(lon),
                lat=float(lat),
                on_ground=on_ground,
                alt_baro_ft=None if on_ground else _int(alt_baro),
                alt_geom_ft=_int(ac.get("alt_geom")),
                gs_kt=_float(ac.get("gs")),
                track_deg=_float(ac.get("track")),
                baro_rate_fpm=_int(ac.get("baro_rate")),
                squawk=ac.get("squawk"),
                source_type=ac.get("type"),
                nic=_int(ac.get("nic")),
                nac_p=_int(ac.get("nac_p")),
                sil=_int(ac.get("sil")),
                rssi_dbfs=_float(ac.get("rssi")),
            ),
            ac,
        )


def _header(result: ParsedFile, rec: dict) -> None:
    rid = rec["receiver_id"]
    if result.receiver_id is None:
        result.receiver_id = rid
    elif rid != result.receiver_id:
        raise InconsistentFile(f"uneinheitliche receiver_id: {result.receiver_id!r} / {rid!r}")
    if rec.get("synthetic") is True:
        result.synthetic = True
    ts = _ts(rec["recorder_ts"])
    result.period_start = min(filter(None, (result.period_start, ts)))
    result.period_end = max(filter(None, (result.period_end, ts)))


def _snapshot(result: ParsedFile, data: dict, seen: set) -> None:
    for pos, ac in _positions(data):
        key = (pos.icao24, pos.ts)
        if key in seen:
            continue
        seen.add(key)
        result.positions.append(pos)
        known = result.aircraft.get(pos.icao24)
        if known is None:
            result.aircraft[pos.icao24] = AircraftSeen(
                pos.icao24, ac.get("r"), ac.get("t"), pos.ts, pos.ts
            )
        else:
            known.registration = ac.get("r") or known.registration
            known.type_code = ac.get("t") or known.type_code
            known.first_seen = min(known.first_seen, pos.ts)
            known.last_seen = max(known.last_seen, pos.ts)


def parse_file(path: Path) -> ParsedFile:
    result = ParsedFile()
    seen: set = set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for raw in f:
            try:
                rec = json.loads(raw)
                if not isinstance(rec, dict):
                    raise TypeError("Zeile ist kein Objekt")
                _header(result, rec)
                kind = rec["type"]
                if kind == "snapshot":
                    _snapshot(result, rec["data"], seen)
                elif kind == "gap":
                    result.gaps.append(Gap(_ts(rec["from"]), _ts(rec["to"]), rec["reason"]))
                elif kind == "clock" and _num(rec.get("offset_s")):
                    result.clock_offset_max_s = max(
                        result.clock_offset_max_s or 0.0, abs(rec["offset_s"])
                    )
                elif kind == "status" and _num(rec.get("free_bytes")):
                    result.receiver_free_bytes = int(rec["free_bytes"])
            except InconsistentFile:
                raise
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                result.bad_lines += 1
    return result
