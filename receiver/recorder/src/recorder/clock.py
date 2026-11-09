"""Messung der Uhrabweichung per SNTP (RFC 4330)."""

from __future__ import annotations

import socket
import struct
import time

NTP_DELTA = 2208988800  # Sekunden zwischen 1900-01-01 und 1970-01-01


def _ntp_time(raw: bytes) -> float:
    sec, frac = struct.unpack("!II", raw)
    return sec - NTP_DELTA + frac / 2**32


def sntp_offset(server: str, port: int = 123, timeout: float = 2.0) -> float | None:
    """Abweichung der Systemuhr zum Server in Sekunden (positiv: Systemuhr geht nach)."""
    request = b"\x1b" + 47 * b"\0"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            t1 = time.time()
            s.sendto(request, (server, port))
            data, _ = s.recvfrom(48)
            t4 = time.time()
    except OSError:
        return None
    if len(data) < 48:
        return None
    t2, t3 = _ntp_time(data[32:40]), _ntp_time(data[40:48])
    return ((t2 - t1) + (t3 - t4)) / 2
