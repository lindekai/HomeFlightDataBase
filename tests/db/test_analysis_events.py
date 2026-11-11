import math
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from synthetic.tracks import add_raw_file, insert_positions, offset, straight

from analysis import db, events
from analysis.config import Config
from analysis.segment import segment
from analysis.zones import Zone, load_zones

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
SPEED_MS = 200 * 1852 / 3600
HALF_CHORD = (5000**2 - 2000**2) ** 0.5


def zone():
    return Zone(
        "Testzone",
        "circle",
        {"type": "Point", "coordinates": [10.0, 50.0]},
        5000.0,
        (10.0, 50.0),
        10000,
        "Test",
    )


def east_track(start=T0, north_m=2000, icao="ff0001"):
    lat, lon = offset(50.0, 10.0, north_m, -20000)
    return straight(start, lat, lon, 90, 200, 400, icao24=icao)


def crossings_for(dsns, rows):
    insert_positions(dsns["admin"], rows)
    cfg = Config(db_dsn=dsns["analysis"], ber_lat=49.0, ber_lon=8.0)
    with psycopg.connect(dsns["analysis"], autocommit=True) as c:
        load_zones(c, [zone()])
        run_id = db.start_run(c, "incremental", "test", cfg.params(), T0, T0)
        found = []
        with c.transaction():
            for icao, pts in db.aircraft_points(c, T0, T0 + timedelta(hours=1), {}):
                for seg in segment(icao, pts, gap_s=600, max_speed_kt=800):
                    fid = db.insert_flight(c, run_id, seg)
                    found += [(seg, cr) for cr in events.crossings(c, fid)]
    return found


def test_straight_crossing_matches_geometry(db_dsns):
    ((seg, c),) = crossings_for(db_dsns, east_track())
    expect_entry = (20000 - HALF_CHORD) / SPEED_MS
    expect_exit = (20000 + HALF_CHORD) / SPEED_MS
    assert abs((c.entry - T0).total_seconds() - expect_entry) < 1
    assert abs((c.exit - T0).total_seconds() - expect_exit) < 1
    assert abs((c.closest - T0).total_seconds() - 20000 / SPEED_MS) < 1
    assert abs(c.min_dist_m - 2000) < 25
    assert events.sector(c.heading_deg) == "O"
    assert len(seg.points) == 400


def test_near_miss_has_no_crossing(db_dsns):
    assert crossings_for(db_dsns, east_track(north_m=6000)) == []


def test_two_passes_give_two_crossings(db_dsns):
    back_lat, back_lon = offset(50.0, 10.0, -2000, 21000)
    # 60 s für den Wechsel auf die Gegenbahn: 4 km Versatz, sonst wäre es ein Ausreißer.
    rows = east_track() + straight(T0 + timedelta(seconds=460), back_lat, back_lon, 270, 200, 400)
    found = crossings_for(db_dsns, rows)
    assert [events.sector(c.heading_deg) for _, c in found] == ["O", "W"]
    assert found[0][1].exit < found[1][1].entry


def test_reception_gap_detection(db_dsns):
    raw_id = add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        c.execute(
            "INSERT INTO reception_gaps (receiver_id, gap_start, gap_end, reason, raw_file_id)"
            " VALUES ('TEST', %s, %s, 'no_data', %s)",
            (T0 + timedelta(seconds=180), T0 + timedelta(seconds=200), raw_id),
        )
    with psycopg.connect(db_dsns["analysis"]) as c:
        assert db.in_reception_gap(c, T0 + timedelta(seconds=150), T0 + timedelta(seconds=240))
        assert not db.in_reception_gap(c, T0, T0 + timedelta(seconds=100))


def diagonal_track(dist_m=3400, heading=45.0, along_m=20000, n=400):
    """Gerade Spur im lokalen Meter-System um 50/10, die das Zentrum mit ``dist_m`` passiert;
    der Lotfußpunkt wird nach ``along_m`` erreicht."""
    h = math.radians(heading)
    perp = h - math.pi / 2  # links der Flugrichtung
    rows = straight(T0, 50.0, 10.0, heading, 200, n)
    for i, r in enumerate(rows):
        s = SPEED_MS * i - along_m
        r["lat"], r["lon"] = offset(
            50.0,
            10.0,
            dist_m * math.cos(perp) + s * math.cos(h),
            dist_m * math.sin(perp) + s * math.sin(h),
        )
    return rows


def test_diagonal_crossing_closest_time_is_geodesic(db_dsns):
    ((_, c),) = crossings_for(db_dsns, diagonal_track())
    assert abs(c.min_dist_m - 3400) < 25
    assert abs((c.closest - T0).total_seconds() - 20000 / SPEED_MS) < 1
