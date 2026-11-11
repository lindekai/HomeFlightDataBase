#!/usr/bin/env python3
"""Prüft eine Verfahrensdatei offline und listet die Verfahren ohne Koordinaten.

Aufruf: python scripts/check_procedures.py config/local/procedures.yaml
Referenzpunkt aus --ber-lat/--ber-lon oder ANALYSIS_BER_LAT/ANALYSIS_BER_LON, Radius für den
Sektor aus --radius-m oder ANALYSIS_BER_RADIUS_M (Standard 40000).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis" / "src"))

from analysis.procedures import Procedure, ProcedureError, read_procedures  # noqa: E402

HEADER = (
    f"{'Name':<10} {'Art':<4} {'Bahn':<4} {'Richtung':<8} {'Sektor':<6} {'Gültigkeit':<23} Länge"
)


def line(p: Procedure) -> str:
    validity = f"{p.valid_from} – {p.valid_to or 'offen'}"
    return (
        f"{p.name:<10} {p.kind:<4} {p.runway:<4} {p.direction:<8} {p.sector:<6} {validity:<23}"
        f" {p.length_m / 1000:.1f} km"
    )


def _env_float(name: str, default: float | None = None) -> float | None:
    value = os.environ.get(name)
    return float(value) if value else default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--ber-lat", type=float, default=_env_float("ANALYSIS_BER_LAT"))
    parser.add_argument("--ber-lon", type=float, default=_env_float("ANALYSIS_BER_LON"))
    parser.add_argument(
        "--radius-m", type=float, default=_env_float("ANALYSIS_BER_RADIUS_M", 40000.0)
    )
    args = parser.parse_args(argv)
    if args.ber_lat is None or args.ber_lon is None:
        print(
            "Referenzpunkt fehlt: --ber-lat/--ber-lon oder ANALYSIS_BER_LAT/_LON", file=sys.stderr
        )
        return 2
    try:
        procedures = read_procedures(
            args.file, ber_lat=args.ber_lat, ber_lon=args.ber_lon, ber_radius_m=args.radius_m
        )
    except ProcedureError as e:
        print(f"ungültig: {e}", file=sys.stderr)
        return 1
    print(HEADER)
    for p in procedures:
        print(line(p))
    print(f"{len(procedures)} Verfahren geprüft")
    return 0


if __name__ == "__main__":
    sys.exit(main())
