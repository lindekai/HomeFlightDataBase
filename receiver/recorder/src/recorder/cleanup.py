"""Löschen quittierter Rohdateien nach Ablauf der Vorhaltezeit."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from recorder.files import COMPLETE_SUFFIX

ACK_SUFFIX = ".ack"


def cleanup(
    complete_dir: Path, acked_dir: Path, retention_days: float, now: datetime
) -> list[Path]:
    """Löscht quittierte Dateien älter als die Vorhaltezeit. Ohne Quittung wird nie gelöscht."""
    cutoff = now.timestamp() - retention_days * 86400
    deleted = []
    for gz in sorted(complete_dir.rglob(f"*{COMPLETE_SUFFIX}")):
        rel = gz.relative_to(complete_dir)
        ack = acked_dir / rel.parent / (rel.name + ACK_SUFFIX)
        if not ack.exists() or gz.stat().st_mtime > cutoff:
            continue
        gz.unlink()
        gz.with_name(gz.name + ".sha256").unlink(missing_ok=True)
        ack.unlink()
        deleted.append(rel)

    # Verwaiste Quittungen (Datei schon gelöscht oder nie vorhanden) nach derselben Frist entfernen.
    for ack in acked_dir.rglob(f"*{ACK_SUFFIX}"):
        rel = ack.relative_to(acked_dir)
        data = complete_dir / rel.parent / rel.name.removesuffix(ACK_SUFFIX)
        if not data.exists() and ack.stat().st_mtime <= cutoff:
            ack.unlink()
    return deleted


def free_space(path: Path) -> tuple[int, float]:
    usage = shutil.disk_usage(path)
    return usage.free, usage.free / usage.total
