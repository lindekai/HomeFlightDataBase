"""Dateinamen, Abschluss und Wiederherstellung von Rohdatendateien."""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

CURRENT_SUFFIX = ".ndjson"
COMPLETE_SUFFIX = ".ndjson.gz"
PARTIAL_MARK = ".partial"


def file_stem(receiver_id: str, start: datetime) -> Path:
    """Relativer Pfad ohne Endung, z. B. ``TEST/2026/11/09/20261109T140000Z``."""
    s = start.astimezone(UTC)
    return Path(receiver_id, f"{s:%Y}", f"{s:%m}", f"{s:%d}", f"{s:%Y%m%dT%H%M%SZ}")


def period_start(ts: datetime, rotate_seconds: int) -> datetime:
    """Beginn der Rotationsperiode, in der ``ts`` liegt (an der Unix-Epoche ausgerichtet)."""
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - epoch % rotate_seconds, tz=UTC)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fsync(path: Path) -> None:
    with path.open("rb") as f:
        os.fsync(f.fileno())


def finalize(
    current_file: Path, current_dir: Path, complete_dir: Path, partial: bool = False
) -> Path:
    """Komprimiert eine Datei aus ``current/`` und verschiebt sie atomar nach ``complete/``.

    Die ``.sha256`` wird zuletzt angelegt – erst dann gilt die Datei als abholbereit.
    """
    rel = current_file.relative_to(current_dir)
    stem = rel.name.removesuffix(CURRENT_SUFFIX)
    name = stem + (PARTIAL_MARK if partial else "") + COMPLETE_SUFFIX
    target = complete_dir / rel.parent / name
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp = target.with_name(f".{name}.tmp")
    with current_file.open("rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    _fsync(tmp)
    digest = sha256_file(tmp)
    os.replace(tmp, target)

    sidecar_tmp = target.with_name(f".{name}.sha256.tmp")
    sidecar_tmp.write_text(f"{digest}  {name}\n", encoding="ascii")
    _fsync(sidecar_tmp)
    os.replace(sidecar_tmp, target.with_name(name + ".sha256"))

    current_file.unlink()
    return target


def truncate_incomplete_line(path: Path) -> None:
    """Schneidet eine unvollständige letzte Zeile ab (nach Absturz oder Stromausfall)."""
    with path.open("r+b") as f:
        pos = f.seek(0, os.SEEK_END)
        while pos > 0:
            step = min(65536, pos)
            pos -= step
            f.seek(pos)
            idx = f.read(step).rfind(b"\n")
            if idx != -1:
                f.truncate(pos + idx + 1)
                return
        f.truncate(0)


def recover(current_dir: Path, complete_dir: Path) -> list[Path]:
    """Schließt beim Start liegengebliebene Dateien als ``.partial`` ab."""
    recovered = []
    for path in sorted(current_dir.rglob(f"*{CURRENT_SUFFIX}")):
        truncate_incomplete_line(path)
        if path.stat().st_size == 0:
            path.unlink()
            continue
        recovered.append(finalize(path, current_dir, complete_dir, partial=True))
    return recovered


def last_activity(*dirs: Path) -> datetime | None:
    """Jüngste Dateiänderung – Näherung für das Ende der letzten Aufzeichnung."""
    latest = max(
        (p.stat().st_mtime for d in dirs if d.exists() for p in d.rglob("*") if p.is_file()),
        default=None,
    )
    return None if latest is None else datetime.fromtimestamp(latest, tz=UTC)
