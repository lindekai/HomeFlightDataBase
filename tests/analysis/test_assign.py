from datetime import UTC, date, datetime

import pytest
from synthetic.routes import LOCAL, THR_09, TWEST, WNMID, WNORD, WSMID, WSUED, fly, points

from analysis.assign import Reference, assign, sector_fit
from analysis.deviation import samples

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
D0 = date(2026, 11, 5)


def ref(rid, name, line, *, kind="SID", direction="west", sector="NW", valid_to=None):
    return Reference(rid, name, kind, direction, sector, line, D0, valid_to)


NORTH = ref(1, "WNORD1W", [THR_09, TWEST, WNMID, WNORD])
SOUTH = ref(2, "WSUED1W", [THR_09, TWEST, WSMID, WSUED], sector="SW")
EAST = ref(3, "ONORD1E", [(1500.0, 0.0), (12000.0, 0.0)], direction="east", sector="NO")
STAR = ref(4, "ONORD1W", [(35000.0, 40000.0), (12000.0, 0.0)], kind="STAR", sector="NO")
ALL = [NORTH, SOUTH, EAST, STAR]
OPTS = {"max_alt_ft": None, "ratio": 2.0}


def north_track(offset_m=0.0):
    """Abflug entlang WNORD1W, um ``offset_m`` nach Norden versetzt."""
    shifted = [(x, y + offset_m) for x, y in [THR_09, TWEST, WNMID, WNORD]]
    return samples(points(fly(shifted, T0)), LOCAL)


def test_sector_fit():
    assert sector_fit("N", "N") == "genau"
    assert sector_fit("N", "NW") == sector_fit("N", "NO") == "ungefähr"
    assert sector_fit("N", "S") is None


def test_high_confidence():
    a = assign("departure", "west", "NW", north_track(), ALL, **OPTS)
    assert (a.reference.name, a.confidence) == ("WNORD1W", "high")
    assert a.mean_dev_m == pytest.approx(0, abs=1e-6)
    assert a.second_mean_dev_m is None  # WSUED1W liegt in SW, kein Nachbarsektor von NW
    assert a.basis == (
        "Betriebsrichtung west. Sektor NW, Verfahren WNORD1W NW: passt genau."
        " Mittlere Abweichung 0 m, kein weiteres Verfahren in Frage."
    )


def test_high_with_distinct_second_candidate():
    upper = ref(5, "OBEN1W", [(-1500.0, 3000.0), (-50000.0, 3000.0)], sector="W")
    lower = ref(6, "UNTEN1W", [(-1500.0, 0.0), (-50000.0, 0.0)], sector="W")
    track = samples(points(fly([(-2000.0, 400.0), (-30000.0, 400.0)], T0)), LOCAL)
    a = assign("departure", "west", "W", track, [upper, lower], **OPTS)
    assert (a.reference.name, a.confidence) == ("UNTEN1W", "high")
    assert (a.mean_dev_m, a.second_mean_dev_m) == (pytest.approx(400), pytest.approx(2600))
    assert "OBEN1W 2600 m (deutlich getrennt)" in a.basis


def test_medium_when_direction_unknown():
    a = assign("departure", "unknown", "NW", north_track(), ALL, **OPTS)
    assert (a.reference.name, a.confidence) == ("WNORD1W", "medium")
    assert "Betriebsrichtung unbekannt" in a.basis


def test_medium_when_sector_only_neighbouring():
    a = assign("departure", "west", "N", north_track(), ALL, **OPTS)
    assert (a.reference.name, a.confidence, a.second_mean_dev_m) == ("WNORD1W", "medium", None)
    assert "passt ungefähr" in a.basis


def test_medium_when_candidates_not_distinct():
    upper = ref(5, "OBEN1W", [(-1500.0, 1000.0), (-50000.0, 1000.0)], sector="W")
    lower = ref(6, "UNTEN1W", [(-1500.0, 0.0), (-50000.0, 0.0)], sector="W")
    track = samples(points(fly([(-2000.0, 400.0), (-30000.0, 400.0)], T0)), LOCAL)
    a = assign("departure", "west", "W", track, [upper, lower], **OPTS)
    assert (a.reference.name, a.confidence) == ("UNTEN1W", "medium")
    assert (a.mean_dev_m, a.second_mean_dev_m) == (pytest.approx(400), pytest.approx(600))
    assert "nicht deutlich getrennt" in a.basis


def test_low_when_two_conditions_fail():
    a = assign("departure", "unknown", "N", north_track(), ALL, **OPTS)
    assert (a.reference.name, a.confidence) == ("WNORD1W", "low")


def test_none_without_candidate():
    a = assign("arrival", "east", "NO", north_track(), ALL, **OPTS)
    assert (a.reference, a.confidence, a.mean_dev_m) == (None, "none", None)
    assert "Kein STAR passt" in a.basis


def test_reference_without_section_is_no_candidate():
    far = ref(7, "FERN1W", [(-60000.0, 0.0), (-90000.0, 0.0)], sector="NW")
    assert assign("departure", "west", "NW", north_track(), [far], **OPTS).confidence == "none"


def test_altitude_limit_applies_to_assignment():
    a = assign("departure", "west", "NW", north_track(), [NORTH], max_alt_ft=400, ratio=2.0)
    assert a.confidence == "none"  # Spur beginnt in 500 ft


def test_valid_on():
    old = ref(8, "ALT1W", NORTH.line, valid_to=date(2026, 11, 9))
    assert old.valid_on(date(2026, 11, 8)) and not old.valid_on(date(2026, 11, 9))
    assert not old.valid_on(date(2026, 11, 4))
