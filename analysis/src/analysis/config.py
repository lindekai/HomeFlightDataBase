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
    "procedures_file",
    "role_near_m",
    "role_max_alt_ft",
    "direction_dist_m",
    "direction_tol_deg",
    "direction_min_flights",
    "direction_min_share",
    "assign_ratio",
    "route_max_alt_ft",
    "corridor_m",
    "corridor_min_s",
    "approach_tol",
    "review_max_gap_s",
)


def _optional(value: str | None, kind):
    return kind(value) if value else None


@dataclass(frozen=True)
class Config:
    db_dsn: str
    ber_lat: float
    ber_lon: float
    zones_file: Path | None = None
    procedures_file: Path | None = None
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
    role_near_m: float = 10000.0
    role_max_alt_ft: int = 3000
    direction_dist_m: float = 15000.0
    direction_tol_deg: float = 30.0
    direction_min_flights: int = 3
    direction_min_share: float = 0.8
    assign_ratio: float = 2.0
    route_max_alt_ft: int | None = None
    corridor_m: float = 1852.0
    corridor_min_s: float = 30.0
    approach_tol_m: float | None = None  # leer: wie corridor_m
    review_max_gap_s: float = 30.0

    @property
    def approach_tol(self) -> float:
        return self.corridor_m if self.approach_tol_m is None else self.approach_tol_m

    def params(self) -> dict:
        values = {name: getattr(self, name) for name in PARAM_FIELDS}
        return {k: str(v) if isinstance(v, Path) else v for k, v in values.items()}

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        return cls(
            db_dsn=env["ANALYSIS_DB_DSN"],
            ber_lat=float(env["ANALYSIS_BER_LAT"]),
            ber_lon=float(env["ANALYSIS_BER_LON"]),
            zones_file=_optional(env.get("ANALYSIS_ZONES_FILE"), Path),
            procedures_file=_optional(env.get("ANALYSIS_PROCEDURES_FILE"), Path),
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
            role_near_m=float(env.get("ANALYSIS_ROLE_NEAR_M", "10000")),
            role_max_alt_ft=int(env.get("ANALYSIS_ROLE_MAX_ALT_FT", "3000")),
            direction_dist_m=float(env.get("ANALYSIS_DIRECTION_DIST_M", "15000")),
            direction_tol_deg=float(env.get("ANALYSIS_DIRECTION_TOL_DEG", "30")),
            direction_min_flights=int(env.get("ANALYSIS_DIRECTION_MIN_FLIGHTS", "3")),
            direction_min_share=float(env.get("ANALYSIS_DIRECTION_MIN_SHARE", "0.8")),
            assign_ratio=float(env.get("ANALYSIS_ASSIGN_RATIO", "2.0")),
            route_max_alt_ft=_optional(env.get("ANALYSIS_ROUTE_MAX_ALT_FT"), int),
            corridor_m=float(env.get("ANALYSIS_CORRIDOR_M", "1852")),
            corridor_min_s=float(env.get("ANALYSIS_CORRIDOR_MIN_S", "30")),
            approach_tol_m=_optional(env.get("ANALYSIS_APPROACH_TOL_M"), float),
            review_max_gap_s=float(env.get("ANALYSIS_REVIEW_MAX_GAP_S", "30")),
        )
