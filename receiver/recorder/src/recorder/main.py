"""Hauptschleife des recorders."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from recorder import __version__
from recorder.cleanup import cleanup, free_space
from recorder.clock import sntp_offset
from recorder.config import Config
from recorder.files import last_activity, recover
from recorder.gaps import GapDetector
from recorder.source import fetch_aircraft
from recorder.timeutil import iso, utcnow
from recorder.writer import RotatingWriter

log = logging.getLogger("recorder")

HOUSEKEEPING_INTERVAL = timedelta(hours=1)
MAX_CLOCK_OFFSET_S = 1.0


class Recorder:
    def __init__(
        self,
        cfg: Config,
        fetch: Callable[[], dict | None] | None = None,
        now_fn: Callable[[], datetime] = utcnow,
        clock_fn: Callable[[], float | None] | None = None,
    ) -> None:
        self.cfg = cfg
        self._fetch = fetch or (lambda: fetch_aircraft(cfg.readsb_url))
        self._now = now_fn
        self._clock = clock_fn or (lambda: sntp_offset(cfg.ntp_server))
        self.current_dir = cfg.data_dir / "current"
        self.complete_dir = cfg.data_dir / "complete"
        self.acked_dir = cfg.data_dir / "acked"
        self.heartbeat = cfg.data_dir / "heartbeat"
        self._writer = RotatingWriter(
            cfg.receiver_id, self.current_dir, self.complete_dir, cfg.rotate_seconds
        )
        self._gaps = GapDetector(cfg.max_data_age_s)
        self._last_data_now: float | None = None
        self._next_housekeeping: datetime | None = None

    def _record(self, kind: str, now: datetime, **fields) -> None:
        rec = {
            "type": kind,
            "recorder_ts": iso(now),
            "receiver_id": self.cfg.receiver_id,
            "recorder_version": __version__,
        }
        if self.cfg.synthetic:
            rec["synthetic"] = True
        rec.update(fields)
        finished = self._writer.write(rec, now)
        if finished is not None:
            log.info("Datei abgeschlossen", extra={"file": str(finished)})

    def start(self) -> None:
        for d in (self.current_dir, self.complete_dir, self.acked_dir):
            d.mkdir(parents=True, exist_ok=True)
        previous = last_activity(self.current_dir, self.complete_dir)
        for path in recover(self.current_dir, self.complete_dir):
            log.warning("Unvollständige Datei abgeschlossen", extra={"file": str(path)})
        if previous is not None:
            now = self._now()
            span = {"from": iso(previous), "to": iso(now)}
            self._record("gap", now, **span, reason="recorder_restart")

    def tick(self) -> None:
        now = self._now()
        data = self._fetch()
        data_ts = datetime.fromtimestamp(data["now"], tz=UTC) if data is not None else None
        gap = self._gaps.observe(now, data_ts)
        if gap is not None:
            self._record("gap", now, **gap)
        if data is not None and data["now"] != self._last_data_now:
            self._record("snapshot", now, data=data)
            self._last_data_now = data["now"]
            if not self._gaps.in_gap:
                self.heartbeat.touch()
        if self._next_housekeeping is None or now >= self._next_housekeeping:
            self._housekeeping(now)
            self._next_housekeeping = now + HOUSEKEEPING_INTERVAL
        finished = self._writer.rotate_if_due(now)
        if finished is not None:
            log.info("Datei abgeschlossen", extra={"file": str(finished)})

    def _housekeeping(self, now: datetime) -> None:
        offset = self._clock()
        self._record("clock", now, offset_s=offset)
        if offset is None:
            log.warning("Uhrabweichung nicht messbar")
        elif abs(offset) > MAX_CLOCK_OFFSET_S:
            log.warning("Uhrabweichung zu groß", extra={"offset_s": offset})

        free_bytes, free_ratio = free_space(self.cfg.data_dir)
        self._record("status", now, free_bytes=free_bytes, free_ratio=round(free_ratio, 4))
        if free_ratio < self.cfg.min_free_ratio:
            log.warning("Pufferspeicher knapp", extra={"free_ratio": free_ratio})

        deleted = cleanup(self.complete_dir, self.acked_dir, self.cfg.retention_days, now)
        if deleted:
            log.info("Quittierte Dateien gelöscht", extra={"count": len(deleted)})

    def stop(self) -> None:
        now = self._now()
        gap = self._gaps.flush(now)
        if gap is not None:
            self._record("gap", now, **gap)
        finished = self._writer.close(partial=True)
        if finished is not None:
            log.info("Datei bei Beenden abgeschlossen", extra={"file": str(finished)})


def run(cfg: Config, stop: threading.Event) -> None:
    rec = Recorder(cfg)
    rec.start()
    log.info("recorder gestartet", extra={"receiver_id": cfg.receiver_id, "version": __version__})
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            rec.tick()
        except Exception:
            log.exception("Fehler in der Hauptschleife")
        stop.wait(max(0.0, 1.0 - (time.monotonic() - t0)))
    rec.stop()
    log.info("recorder beendet")
