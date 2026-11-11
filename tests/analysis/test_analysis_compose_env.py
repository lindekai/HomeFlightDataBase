"""Der NAS-Stack reicht alle dokumentierten ANALYSIS_*-Variablen mit passendem Standard durch."""

import re
from pathlib import Path

from analysis.config import Config

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {"ANALYSIS_DB_DSN", "ANALYSIS_BER_LAT", "ANALYSIS_BER_LON"}


def _documented() -> set[str]:
    text = (ROOT / "docs" / "analysis.md").read_text(encoding="utf-8")
    section = text.split("## Parameter", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"`(ANALYSIS_[A-Z_]+)`", section))


def _compose_defaults() -> dict[str, str]:
    text = (ROOT / "nas" / "docker-compose.yml").read_text(encoding="utf-8")
    return dict(re.findall(r"(ANALYSIS_[A-Z_]+): \$\{\1:-([^}]+)\}", text))


def test_compose_passes_documented_analysis_vars():
    defaults = _compose_defaults()
    missing = _documented() - REQUIRED - set(defaults)
    assert missing == set()


def test_compose_defaults_match_config():
    base = {"ANALYSIS_DB_DSN": "x", "ANALYSIS_BER_LAT": "0", "ANALYSIS_BER_LON": "0"}
    defaults = _compose_defaults()
    assert defaults
    assert Config.from_env(base) == Config.from_env(base | defaults)
