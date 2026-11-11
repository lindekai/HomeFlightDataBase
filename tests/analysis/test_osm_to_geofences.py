import pytest
from osm_to_geofences import convert, rings

from analysis.zones import parse_zones


def way(*coords):
    return {
        "type": "way",
        "role": "outer",
        "geometry": [{"lat": la, "lon": lo} for la, lo in coords],
    }


def relation(name, members):
    return {
        "type": "relation",
        "id": 1,
        "tags": {"name": name, "boundary": "administrative"},
        "members": members,
    }


SQUARE = [
    way((44.0, -31.0), (44.0, -30.9), (44.1, -30.9)),
    way((44.0, -31.0), (44.1, -31.0), (44.1, -30.9)),  # andersherum orientiert
]


def test_rings_joins_and_closes():
    (ring,) = rings(
        [
            [(-31.0, 44.0), (-30.9, 44.0)],
            [(-30.9, 44.0), (-30.9, 44.1)],
            [(-31.0, 44.0), (-30.9, 44.1)],
        ]
    )
    assert ring[0] == ring[-1] and len(ring) == 4


def test_rings_rejects_open_boundary():
    with pytest.raises(ValueError, match="geschlossen"):
        rings([[(-31.0, 44.0), (-30.9, 44.0)]])


def test_convert_relation_and_circle():
    data = {"elements": [relation("Beispielort", SQUARE)]}
    out = convert(
        data,
        source="OSM, ODbL, Abruf 2026-11-10",
        circles=["Nahbereich,45.0,-30.0,1500"],
        relevance_ft=8000,
    )
    zones = parse_zones(out, 10000)
    assert [(z.name, z.kind) for z in zones] == [
        ("Beispielort", "polygon"),
        ("Nahbereich", "circle"),
    ]
    assert zones[0].source == "OSM, ODbL, Abruf 2026-11-10"
    assert all(z.relevance_max_alt_ft == 8000 for z in zones)
    assert zones[1].radius_m == 1500 and zones[1].ref_point == (-30.0, 45.0)


def test_inner_ring_becomes_hole():
    hole = {
        "type": "way",
        "role": "inner",
        "geometry": [
            {"lat": 44.04, "lon": -30.96},
            {"lat": 44.04, "lon": -30.94},
            {"lat": 44.06, "lon": -30.94},
            {"lat": 44.04, "lon": -30.96},
        ],
    }
    out = convert(
        {"elements": [relation("Mit Loch", [*SQUARE, hole])]},
        source="t",
        circles=[],
        relevance_ft=None,
    )
    geometry = out["features"][0]["geometry"]
    assert geometry["type"] == "Polygon"
    assert len(geometry["coordinates"]) == 2  # Außenring + Loch
