"""Erkennung von Zeiträumen ohne frische readsb-Daten."""

from __future__ import annotations

from datetime import datetime

from recorder.timeutil import iso


class GapDetector:
    """Meldet eine Lücke, sobald wieder frische Daten kommen oder beim Beenden."""

    def __init__(self, max_age_s: float) -> None:
        self._max_age_s = max_age_s
        self._last_good: datetime | None = None
        self._gap_start: datetime | None = None
        self._reason = ""

    @property
    def in_gap(self) -> bool:
        return self._gap_start is not None

    def observe(self, now: datetime, data_ts: datetime | None) -> dict | None:
        fresh = data_ts is not None and (now - data_ts).total_seconds() <= self._max_age_s
        if not fresh:
            if self._gap_start is None:
                self._gap_start = self._last_good or now
                self._reason = "no_data" if data_ts is None else "stale_data"
            return None
        gap = self.flush(now)
        self._last_good = now
        return gap

    def flush(self, now: datetime) -> dict | None:
        if self._gap_start is None:
            return None
        gap = {"from": iso(self._gap_start), "to": iso(now), "reason": self._reason}
        self._gap_start = None
        return gap
