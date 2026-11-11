import math

import psycopg
import pytest

from analysis.zones import Zone, ZoneError, load_zones

pytestmark = pytest.mark.db


def circle(name="Testzone", radius=5000.0, relevance=10000):
    return Zone(
        name,
        "circle",
        {"type": "Point", "coordinates": [10.0, 50.0]},
        radius,
        (10.0, 50.0),
        relevance,
        "Test",
    )


def square(name="Feld", ref=None):
    ring = [[10.0, 50.0], [10.1, 50.0], [10.1, 50.1], [10.0, 50.1], [10.0, 50.0]]
    return Zone(name, "polygon", {"type": "Polygon", "coordinates": [ring]}, None, ref, 10000, None)


def rows(dsn):
    with psycopg.connect(dsn) as c:
        return c.execute(
            "SELECT name, radius_m, valid_to IS NULL FROM geofences ORDER BY id"
        ).fetchall()


def test_circle_area_and_ref_point(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        assert load_zones(c, [circle()]).changed == ["Testzone"]
        area, ref_ok = c.execute(
            "SELECT ST_Area(geom::geography), ST_Equals(ref_point, ST_SetSRID("
            "ST_MakePoint(10, 50), 4326)) FROM geofences"
        ).fetchone()
    assert abs(area / (math.pi * 5000**2) - 1) < 0.005
    assert ref_ok


def test_unchanged_reload_keeps_version(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_zones(c, [circle()])
        result = load_zones(c, [circle()])
    assert (result.changed, result.removed) == ([], [])
    assert rows(db_dsns["admin"]) == [("Testzone", 5000.0, True)]


def test_changed_zone_gets_new_version(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_zones(c, [circle()])
        assert load_zones(c, [circle(radius=3000)]).changed == ["Testzone"]
    assert rows(db_dsns["admin"]) == [("Testzone", 5000.0, False), ("Testzone", 3000.0, True)]


def test_removed_zone_is_closed(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_zones(c, [circle(), square()])
        assert load_zones(c, [circle()]).removed == ["Feld"]
    assert ("Feld", None, False) in rows(db_dsns["admin"])


def test_polygon_default_ref_point_inside(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_zones(c, [square()])
        assert c.execute("SELECT ST_Within(ref_point, geom) FROM geofences").fetchone() == (True,)


def test_invalid_polygon_writes_nothing(db_dsns):
    bowtie = [[10.0, 50.0], [10.1, 50.1], [10.1, 50.0], [10.0, 50.1], [10.0, 50.0]]
    bad = Zone(
        "Schleife", "polygon", {"type": "Polygon", "coordinates": [bowtie]}, None, None, 10000, None
    )
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        with pytest.raises(ZoneError, match="ungültig"):
            load_zones(c, [circle(), bad])
    assert rows(db_dsns["admin"]) == []
