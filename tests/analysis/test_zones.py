import json

import pytest

from analysis.zones import ZoneError, parse_zones, read_zones

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-31, 44], [-30.9, 44], [-30.9, 44.1], [-31, 44.1], [-31, 44]]],
}


def fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def feature(geometry, **props):
    return {"type": "Feature", "geometry": geometry, "properties": props}


def test_circle_and_polygon():
    zones = parse_zones(
        fc(
            feature({"type": "Point", "coordinates": [-30.0, 45.0]}, name="Kreis", radius_m=3000),
            feature(SQUARE, name="Feld", relevance_max_alt_ft=5000, source="Test"),
        ),
        default_relevance_ft=10000,
    )
    circle, square = zones
    assert (circle.kind, circle.radius_m, circle.ref_point) == ("circle", 3000, (-30.0, 45.0))
    assert circle.relevance_max_alt_ft == 10000
    assert (square.kind, square.ref_point, square.relevance_max_alt_ft) == ("polygon", None, 5000)
    assert square.source == "Test"


def test_polygon_ref_point():
    (z,) = parse_zones(fc(feature(SQUARE, name="Feld", ref_point=[-30.95, 44.05])), 10000)
    assert z.ref_point == (-30.95, 44.05)


@pytest.mark.parametrize(
    "data, message",
    [
        ({"type": "Feature"}, "FeatureCollection"),
        (fc(), "keine Zonen"),
        (fc(feature(SQUARE)), "name"),
        (fc(feature(SQUARE, name="A"), feature(SQUARE, name="A")), "doppelt"),
        (fc(feature({"type": "Point", "coordinates": [-30, 45]}, name="K")), "radius_m"),
        (
            fc(feature({"type": "Point", "coordinates": [-30, 45]}, name="K", radius_m=0)),
            "radius_m",
        ),
        (fc(feature({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, name="L")), "Typ"),
        (fc(feature(SQUARE, name="F", ref_point=[200, 44])), "ref_point"),
    ],
)
def test_invalid_zones(data, message):
    with pytest.raises(ZoneError, match=message):
        parse_zones(data, 10000)


def test_example_file_is_valid():
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / "config" / "geofences.example.geojson"
    zones = read_zones(example, 10000)
    assert {z.kind for z in zones} == {"circle", "polygon"}
    # Beispiel liegt im Atlantik, weit weg von jedem echten Ort.
    assert all(z.ref_point is None or z.ref_point[0] < -20 for z in zones)


def test_read_zones_reports_bad_json(tmp_path):
    p = tmp_path / "z.geojson"
    p.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(ZoneError, match="JSON"):
        read_zones(p, 10000)
    p.write_text(json.dumps(fc()), encoding="utf-8")
    with pytest.raises(ZoneError):
        read_zones(p, 10000)
