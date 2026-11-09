import socket
import struct
import threading
import time

from recorder.clock import NTP_DELTA, sntp_offset


def fake_ntp_server(skew_s):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))

    def serve():
        _, addr = sock.recvfrom(48)
        t = time.time() + skew_s + NTP_DELTA
        sec, frac = int(t), int((t % 1) * 2**32)
        reply = bytearray(48)
        reply[0] = 0x1C
        reply[32:40] = struct.pack("!II", sec, frac)
        reply[40:48] = struct.pack("!II", sec, frac)
        sock.sendto(bytes(reply), addr)
        sock.close()

    threading.Thread(target=serve, daemon=True).start()
    return sock.getsockname()[1]


def test_measures_offset():
    port = fake_ntp_server(10.0)
    offset = sntp_offset("127.0.0.1", port=port)
    assert offset is not None
    assert abs(offset - 10.0) < 0.5


def test_unreachable_returns_none():
    assert sntp_offset("127.0.0.1", port=9, timeout=0.3) is None
