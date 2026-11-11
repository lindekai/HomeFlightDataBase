"""Ersetzt Grafana-Variablen (und optional Makros) in Panel-SQL für Tests."""

from __future__ import annotations

import re

VARIABLES = [
    (r"\(\$zone\)", "('Testzone')"),
    (r"\(\$category\)", "('arrival', 'departure', 'overflight', 'unknown')"),
    (r"'\$relevant'", "'alle'"),
    (r"'\$bucket'", "'day'"),
    (r"\(\$procedure\)", "('WNORD1W', 'ONORD1W')"),
    (r"'\$confidence'", "'alle'"),
    (r"'\$only_review'", "'nein'"),
]
MACROS = [
    (r"\$__timeFilter\(([^)]+)\)", r"\1 BETWEEN '2026-01-01T00:00:00Z' AND '2027-01-01T00:00:00Z'"),
    (r"\$__timeFrom\(\)", "'2026-01-01T00:00:00Z'"),
    (r"\$__timeTo\(\)", "'2027-01-01T00:00:00Z'"),
]


def sqlstring(value: str) -> str:
    """Wie Grafanas Format ``${var:sqlstring}``: in einfache Anführungszeichen, ' verdoppelt."""
    return "'" + value.replace("'", "''") + "'"


def substitute(sql: str, *, macros: bool = True, flight_id: str = "0") -> str:
    sql = sql.replace("${flight_id:sqlstring}", sqlstring(flight_id))
    sql = re.sub(r"\$flight_id\b", lambda _: flight_id, sql)
    for pattern, repl in VARIABLES + (MACROS if macros else []):
        sql = re.sub(pattern, repl, sql)
    return sql
