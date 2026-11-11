"""Konfiguration aus Umgebungsvariablen."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Werte, die das Ergebnis beeinflussen; werden je Lauf in analysis_runs.params festgehalten.
PARAM_FIELDS = (
    "settle_s",
    "flight_gap_s",
    "max_speed_kt",
    "context_s",
    "min_positions",
    "vrate_fpm",
    "ber_radius_m",
    "ber_lat",
    "ber_lon",
)


@dataclass(frozen=True)
class Config:
    db_dsn: str
    ber_lat: float
    ber_lon: float
    zones_file: Path | None = None
    interval_s: int = 300
    settle_s: int = 120
    flight_gap_s: int = 600
    max_speed_kt: float = 800.0
    context_s: int = 120
    min_positions: int = 5
    vrate_fpm: float = 300.0
    ber_radius_m: float = 40000.0
    default_relevance_ft: int = 10000
    max_lag_s: int = 10800
    heartbeat_file: Path = Path("/tmp/analysis-heartbeat")

    def params(self) -> dict:
        return {name: getattr(self, name) for name in PARAM_FIELDS}

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        zones = env.get("ANALYSIS_ZONES_FILE")
        return cls(
            db_dsn=env["ANALYSIS_DB_DSN"],
            ber_lat=float(env["ANALYSIS_BER_LAT"]),
            ber_lon=float(env["ANALYSIS_BER_LON"]),
            zones_file=Path(zones) if zones else None,
            interval_s=int(env.get("ANALYSIS_INTERVAL_S", "300")),
            settle_s=int(env.get("ANALYSIS_SETTLE_S", "120")),
            flight_gap_s=int(env.get("ANALYSIS_FLIGHT_GAP_S", "600")),
            max_speed_kt=float(env.get("ANALYSIS_MAX_SPEED_KT", "800")),
            context_s=int(env.get("ANALYSIS_CONTEXT_S", "120")),
            min_positions=int(env.get("ANALYSIS_MIN_POSITIONS", "5")),
            vrate_fpm=float(env.get("ANALYSIS_VRATE_FPM", "300")),
            ber_radius_m=float(env.get("ANALYSIS_BER_RADIUS_M", "40000")),
            default_relevance_ft=int(env.get("ANALYSIS_DEFAULT_RELEVANCE_FT", "10000")),
            max_lag_s=int(env.get("ANALYSIS_MAX_LAG_S", "10800")),
            heartbeat_file=Path(env.get("ANALYSIS_HEARTBEAT_FILE", "/tmp/analysis-heartbeat")),
        )
