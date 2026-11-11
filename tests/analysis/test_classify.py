from datetime import UTC, datetime, timedelta

from analysis.classify import classify
from analysis.segment import Point

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
# Synthetischer Referenzpunkt (50° N / 10° O), kein realer Flughafen.
BER = {"ber_lat": 50.0, "ber_lon": 10.0}
OPTS = BER | {"min_positions": 5, "vrate_fpm": 300, "ber_radius_m": 40000}
M_PER_DEG_LAT = 111_195.0


def line(from_km, to_km, vrate, n=10, alt0=5000, with_rate=True, step_s=6):
    """Punkte südlich des Referenzpunkts auf dem Meridian, Abstand von from_km nach to_km."""
    pts = []
    for i in range(n):
        d = from_km + (to_km - from_km) * i / (n - 1)
        alt = round(alt0 + vrate * step_s * i / 60)
        pts.append(
            Point(
                T0 + timedelta(seconds=step_s * i),
                50.0 - d * 1000 / M_PER_DEG_LAT,
                10.0,
                alt,
                vrate if with_rate else None,
                "TEST01",
                False,
            )
        )
    return pts


def test_arrival():
    c = classify(line(30, 20, -800), **OPTS)
    assert c.category == "arrival"
    assert c.basis["vrate_fpm"] == -800 and c.basis["vrate_source"] == "baro_rate"
    assert abs(c.basis["ber_dist_change_m"] + 10_000) < 50
    assert c.basis["thresholds"]["vrate_fpm"] == 300


def test_departure():
    assert classify(line(20, 30, 1500), **OPTS).category == "departure"


def test_level_flight_is_overflight():
    assert classify(line(30, 20, 0), **OPTS).category == "overflight"


def test_far_from_airport_is_overflight():
    assert classify(line(60, 50, -800), **OPTS).category == "overflight"


def test_climbing_while_approaching_is_unknown():
    c = classify(line(30, 20, 1500), **OPTS)
    assert c.category == "unknown" and "widerspricht" in c.basis["reason"]


def test_too_few_positions_is_unknown():
    c = classify(line(30, 20, -800, n=4), **OPTS)
    assert c.category == "unknown" and c.basis["n_positions"] == 4


def test_rate_from_altitude_when_baro_rate_missing():
    c = classify(line(30, 20, -1000, with_rate=False), **OPTS)
    assert c.category == "arrival" and c.basis["vrate_source"] == "altitude"
    assert abs(c.basis["vrate_fpm"] + 1000) <= 2


def test_threshold_is_strict():
    assert classify(line(30, 20, -300), **OPTS).category == "overflight"
