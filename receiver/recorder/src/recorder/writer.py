"""Zeilenweises Schreiben in rotierende Rohdatendateien."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from recorder.files import CURRENT_SUFFIX, file_stem, finalize, period_start


class RotatingWriter:
    def __init__(
        self, receiver_id: str, current_dir: Path, complete_dir: Path, rotate_seconds: int
    ) -> None:
        self._receiver_id = receiver_id
        self._current_dir = current_dir
        self._complete_dir = complete_dir
        self._rotate_seconds = rotate_seconds
        self._fh: BinaryIO | None = None
        self._path: Path | None = None
        self._period: datetime | None = None

    def write(self, record: dict, ts: datetime) -> Path | None:
        """Hängt ``record`` als JSON-Zeile an; gibt eine dabei abgeschlossene Datei zurück."""
        finished = self.rotate_if_due(ts)
        if self._fh is None:
            stem = file_stem(self._receiver_id, ts)
            self._path = self._current_dir / stem.with_name(stem.name + CURRENT_SUFFIX)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("ab")
            self._period = period_start(ts, self._rotate_seconds)
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        self._fh.write(line.encode("utf-8"))
        self._fh.flush()
        return finished

    def rotate_if_due(self, ts: datetime) -> Path | None:
        if self._fh is not None and period_start(ts, self._rotate_seconds) != self._period:
            return self.close()
        return None

    def close(self, partial: bool = False) -> Path | None:
        if self._fh is None:
            return None
        os.fsync(self._fh.fileno())
        self._fh.close()
        path = self._path
        self._fh = self._path = self._period = None
        return finalize(path, self._current_dir, self._complete_dir, partial=partial)
