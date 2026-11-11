"""Der NAS-Stack reicht alle dokumentierten ANALYSIS_*-Variablen mit passendem Standard durch."""

import re
from pathlib import Path

from analysis.config import Config

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {"ANALYSIS_DB_DSN", "ANALYSIS_BER_LAT", "ANALYSIS_BER_LON"}
# Feste Pfade im Container, kein Standardwert über .env
FIXED = {"ANALYSIS_ZONES_FILE", "ANALYSIS_PROCEDURES_FILE"}


def _documented() -> set[str]:
    text = (ROOT / "docs" / "analysis.md").read_text(encoding="utf-8")
    section = text.split("## Parameter", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"`(ANALYSIS_[A-Z_]+)`", section))


def _compose() -> str:
    return (ROOT / "nas" / "docker-compose.yml").read_text(encoding="utf-8")


def _compose_defaults() -> dict[str, str]:
    # Leerer Standard (``${X:-}``) bedeutet „nicht gesetzt“.
    return dict(re.findall(r"(ANALYSIS_[A-Z_]+): \$\{\1:-([^}]*)\}", _compose()))


def test_compose_passes_documented_analysis_vars():
    passed = set(re.findall(r"^\s+(ANALYSIS_[A-Z_]+):", _compose(), re.M))
    assert _documented() - passed == set()
    missing = _documented() - REQUIRED - FIXED - set(_compose_defaults())
    assert missing == set()


def test_compose_defaults_match_config():
    base = {"ANALYSIS_DB_DSN": "x", "ANALYSIS_BER_LAT": "0", "ANALYSIS_BER_LON": "0"}
    defaults = _compose_defaults()
    assert defaults
    assert Config.from_env(base) == Config.from_env(base | defaults)
