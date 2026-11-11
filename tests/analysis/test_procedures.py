import copy
from datetime import date
from pathlib import Path

import pytest

from analysis.procedures import (
    ProcedureError,
    direction_class,
    opposite_runway,
    parse_coord,
    parse_procedures,
    read_procedures,
)

ROOT = Path(__file__).resolve().parents[2]
BER = {"ber_lat": 45.0, "ber_lon": -30.0, "ber_radius_m": 40000.0}
DATA = {
    "source": "erfunden",
    "waypoints": {
        "WESTA": "45 00 00.00N 030 30 00.00W",
        "NORDA": [45.4, -30.6],
        "OSTAA": [45.0, -29.5],
        "OSTAB": [45.2, -29.2],
    },
    "runways": {"27": [45.0, -29.98], "09": [45.0, -30.02]},
    "procedures": [
        {
            "name": "WESTA1W",
            "kind": "SID",
            "runway": "27",
            "valid_from": date(2026, 11, 5),
            "valid_to": None,
            "airac": "2611",
            "route": ["WESTA", "NORDA"],
            "constraints": {"WESTA": {"alt_ft_min": 5000}},
        },
        {
            "name": "OSTAB1W",
            "kind": "STAR",
            "runway": "27",
            "valid_from": "2026-11-05",
            "route": ["OSTAB", "OSTAA"],
        },
    ],
}


def data(**changes):
    d = copy.deepcopy(DATA)
    for path, value in changes.items():
        *keys, last = path.split("__")
        target = d
        for k in keys:
            target = target[int(k)] if isinstance(target, list) else target[k]
        target[int(last) if isinstance(target, list) else last] = value
    return d


def test_coordinates_dms_and_decimal():
    assert parse_coord("45 30 15.50N 030 05 00.00W", "x") == pytest.approx((45.504306, -30.083333))
    assert parse_coord("453015.50N0300500.00W", "x") == pytest.approx((45.504306, -30.083333))
    assert parse_coord([45.4, -30.6], "x") == (45.4, -30.6)


def test_geometry_direction_and_sector():
    sid, star = parse_procedures(DATA, **BER)
    assert sid.line[0] == (45.0, -30.02)  # SID beginnt an der Gegenschwelle 09
    assert sid.line[1] == pytest.approx((45.0, -30.5))
    assert (sid.runway_heading_deg, sid.direction, sid.sector) == (270.0, "west", "W")
    assert (sid.waypoints, sid.airac, sid.source) == (("WESTA", "NORDA"), "2611", "erfunden")
    assert sid.constraints == {"WESTA": {"alt_ft_min": 5000}}
    assert sid.length_m == 82904
    assert star.line[0] == (45.2, -29.2)  # STAR ohne Endanflug
    assert (star.direction, star.sector, star.valid_from, star.valid_to) == (
        "west",
        "O",
        date(2026, 11, 5),
        None,
    )


def test_east_runway():
    (sid, _) = parse_procedures(data(procedures__0__runway="09"), **BER)
    assert (sid.runway_heading_deg, sid.direction) == (90.0, "east")
    assert sid.line[0] == (45.0, -29.98)


def test_sector_of_line_entirely_inside_radius():
    sid, star = parse_procedures(DATA, **(BER | {"ber_radius_m": 100000.0}))
    assert (sid.sector, star.sector) == ("NW", "O")  # letzter bzw. erster Wegpunkt


def test_opposite_runway_and_direction_class():
    assert [opposite_runway(r) for r in ("25R", "07L", "36", "18", "09C", "01")] == [
        "07L",
        "25R",
        "18",
        "36",
        "27C",
        "19",
    ]
    assert [direction_class(h) for h in (0, 179.9, 180, 359.9)] == ["east", "east", "west", "west"]


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"procedures__0__route": ["WESTA", "XXXXX"]}, "Wegpunkt 'XXXXX' unbekannt"),
        ({"procedures__0__runway": "25L"}, "Startbahn '25L' unbekannt"),
        ({"runways": {"27": [45.0, -29.98]}}, "Gegenschwelle 09 unbekannt"),
        ({"waypoints__WESTA": "45 00 N"}, "WESTA, Feld Koordinate: Koordinate unlesbar"),
        ({"waypoints__NORDA": [95.0, -30.0]}, "außerhalb ±90/±180"),
        ({"waypoints__NORDA": [47.0, -30.0]}, "weiter als 200 km"),
        ({"runways__27": "45 00 00.00N 029 58 61.00W"}, "Startbahn 27, Feld Schwelle"),
        ({"procedures__0__route": []}, "mindestens einen Wegpunkt"),
        ({"procedures__1__route": ["OSTAA"]}, "mindestens zwei Wegpunkte"),
        ({"procedures__0__valid_to": date(2026, 11, 1)}, "valid_to: liegt vor valid_from"),
        ({"procedures__0__valid_from": "05.11.2026"}, "valid_from: Datum JJJJ-MM-TT"),
        ({"procedures__0__kind": "APP"}, "SID oder STAR"),
        ({"procedures__1__name": "WESTA1W"}, "WESTA1W, Feld name: doppelt"),
        ({"procedures": []}, "Feld procedures: fehlt oder leer"),
    ],
)
def test_rejected(changes, message):
    with pytest.raises(ProcedureError, match=message):
        parse_procedures(data(**changes), **BER)


def test_same_name_without_overlap_is_allowed():
    d = data(procedures__1__name="WESTA1W", procedures__1__kind="SID")
    d["procedures"][0]["valid_to"] = date(2026, 12, 3)
    d["procedures"][1]["valid_from"] = date(2026, 12, 3)
    old, new = parse_procedures(d, **BER)
    assert (old.name, new.name) == ("WESTA1W", "WESTA1W")


def test_messages_contain_no_coordinates():
    with pytest.raises(ProcedureError) as e:
        parse_procedures(data(waypoints__NORDA=[47.0, -30.0]), **BER)
    assert "47" not in str(e.value) and "30" not in str(e.value)


def test_content_hash_reflects_content():
    a = parse_procedures(DATA, **BER)[0]
    b = parse_procedures(data(), **BER)[0]
    c = parse_procedures(data(procedures__0__airac="2612"), **BER)[0]
    assert a.content_hash() == b.content_hash() != c.content_hash()


def test_yaml_duplicate_key_and_syntax(tmp_path):
    dup = tmp_path / "dup.yaml"
    dup.write_text("waypoints:\n  WESTA: [45.0, -30.5]\n  WESTA: [45.1, -30.5]\n", "utf-8")
    with pytest.raises(ProcedureError, match="Zeile 3: Name 'WESTA' doppelt"):
        read_procedures(dup, **BER)
    bad = tmp_path / "bad.yaml"
    bad.write_text("waypoints:\n  WESTA: [45.0, -30.5\n", "utf-8")
    with pytest.raises(ProcedureError, match=r"bad.yaml: kein gültiges YAML \(Zeile \d+\)") as e:
        read_procedures(bad, **BER)
    assert "45.0" not in str(e.value)
    with pytest.raises(ProcedureError, match="nicht lesbar"):
        read_procedures(tmp_path / "fehlt.yaml", **BER)


def test_example_files_are_valid():
    example = read_procedures(ROOT / "config" / "procedures.example.yaml", **BER)
    assert {p.kind for p in example} == {"SID", "STAR"}
    fixture = read_procedures(
        ROOT / "tests" / "fixtures" / "procedures.test.yaml",
        ber_lat=50.0,
        ber_lon=10.0,
        ber_radius_m=40000.0,
    )
    assert [(p.name, p.direction, p.sector) for p in fixture] == [
        ("WNORD1W", "west", "NW"),
        ("WSUED1W", "west", "SW"),
        ("ONORD1W", "west", "NO"),
        ("OSUED1W", "west", "SO"),
        ("ONORD1E", "east", "NO"),
        ("OSUED1E", "east", "SO"),
        ("WNORD1E", "east", "NW"),
        ("WSUED1E", "east", "SW"),
    ]
