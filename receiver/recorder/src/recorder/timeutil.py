"""Zeitfunktionen; alle Zeitstempel sind UTC."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    """ISO-8601 mit Millisekunden und ``Z``, z. B. ``2026-11-09T14:00:00.000Z``."""
    return ts.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
