"""Erzeugt synthetische Rohdateien genau so, wie der recorder sie schreibt."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from recorder.timeutil import iso
from recorder.writer import RotatingWriter


def line(kind: str, ts: datetime, receiver_id: str = "TEST", **fields) -> dict:
    return {
        "type": kind,
        "recorder_ts": iso(ts),
        "receiver_id": receiver_id,
        "recorder_version": "test",
        "synthetic": True,
        **fields,
    }


def write_raw_file(
    complete_dir: Path,
    start: datetime,
    snapshots: list[dict],
    receiver_id: str = "TEST",
    extra: list[dict] = (),
) -> Path:
    """Eine Momentaufnahme je Sekunde ab ``start``, danach ``extra``-Zeilen; mit .sha256."""
    current = complete_dir.parent / ".fixture-current"
    writer = RotatingWriter(receiver_id, current, complete_dir, 3600)
    for i, data in enumerate(snapshots):
        ts = start + timedelta(seconds=i)
        writer.write(line("snapshot", ts, receiver_id, data=data), ts)
    for rec in extra:
        writer.write(rec, start)
    return writer.close()
