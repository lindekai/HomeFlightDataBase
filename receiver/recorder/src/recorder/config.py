"""Konfiguration aus Umgebungsvariablen."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    receiver_id: str
    readsb_url: str
    data_dir: Path = Path("/data")
    rotate_seconds: int = 3600
    max_data_age_s: float = 5.0
    retention_days: float = 7
    min_free_ratio: float = 0.10
    ntp_server: str = "pool.ntp.org"
    synthetic: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        return cls(
            receiver_id=env["RECEIVER_ID"],
            readsb_url=env["READSB_URL"],
            data_dir=Path(env.get("RECORDER_DATA_DIR", "/data")),
            rotate_seconds=int(env.get("RECORDER_ROTATE_SECONDS", "3600")),
            max_data_age_s=float(env.get("RECORDER_MAX_DATA_AGE_S", "5")),
            retention_days=float(env.get("RECEIVER_RETENTION_DAYS", "7")),
            min_free_ratio=float(env.get("RECORDER_MIN_FREE_RATIO", "0.10")),
            ntp_server=env.get("RECORDER_NTP_SERVER", "pool.ntp.org"),
            synthetic=env.get("RECORDER_SYNTHETIC", "0") == "1",
        )
