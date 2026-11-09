"""Healthcheck: gesund, wenn der Heartbeat jünger als ``max_age_s`` ist."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main(path: Path | None = None, max_age_s: float = 10.0) -> int:
    path = path or Path(os.environ.get("RECORDER_DATA_DIR", "/data")) / "heartbeat"
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return 1
    return 0 if age <= max_age_s else 1


if __name__ == "__main__":
    sys.exit(main())
