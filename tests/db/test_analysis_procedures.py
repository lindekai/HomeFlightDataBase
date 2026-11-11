import psycopg
import pytest
from synthetic.routes import PROCEDURES_FILE

from analysis.procedures import load_procedures, read_procedures

pytestmark = pytest.mark.db

BER = {"ber_lat": 50.0, "ber_lon": 10.0, "ber_radius_m": 40000.0}


def procedures(text=None, tmp_path=None):
    if text is None:
        return read_procedures(PROCEDURES_FILE, **BER)
    path = tmp_path / "procedures.yaml"
    path.write_text(text, encoding="utf-8")
    return read_procedures(path, **BER)


def rows(dsn):
    with psycopg.connect(dsn) as c:
        return c.execute(
            "SELECT name, airac, superseded_at IS NULL FROM procedures ORDER BY id"
        ).fetchall()


def test_load_stores_geometry_and_attributes(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        result = load_procedures(c, procedures())
        assert len(result.changed) == 8 and result.removed == []
        row = c.execute(
            "SELECT kind, runway, runway_heading_deg, direction, sector, ST_NPoints(geom),"
            " ST_SRID(geom), waypoints, constraints, round(ST_Length(geom::geography))"
            " FROM procedures WHERE name = 'WNORD1W'"
        ).fetchone()
    assert row == (
        "SID",
        "27",
        270.0,
        "west",
        "NW",
        4,
        4326,
        ["TWEST", "WNMID", "WNORD"],
        {"TWEST": {"alt_ft_min": 3000}},
        pytest.approx(59896, rel=0.005),  # Kugel in Python, Ellipsoid in PostGIS
    )


def test_unchanged_reload_keeps_version(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_procedures(c, procedures())
        result = load_procedures(c, procedures())
    assert (result.changed, result.removed) == ([], [])
    assert len(rows(db_dsns["admin"])) == 8


def test_changed_procedure_gets_new_version(db_dsns, tmp_path):
    text = PROCEDURES_FILE.read_text("utf-8").replace(
        'name: WNORD1W, kind: SID, runway: "27", valid_from: 2026-11-05, valid_to: null,\n'
        '     airac: "2611"',
        'name: WNORD1W, kind: SID, runway: "27", valid_from: 2026-11-05, valid_to: null,\n'
        '     airac: "2612"',
    )
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_procedures(c, procedures())
        assert load_procedures(c, procedures(text, tmp_path)).changed == ["WNORD1W"]
    wnord = [r for r in rows(db_dsns["admin"]) if r[0] == "WNORD1W"]
    assert wnord == [("WNORD1W", "2611", False), ("WNORD1W", "2612", True)]


def test_removed_procedure_is_superseded(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_procedures(c, procedures())
        result = load_procedures(c, [p for p in procedures() if p.name != "WSUED1E"])
    assert result.removed == ["WSUED1E"]
    assert ("WSUED1E", "2611", False) in rows(db_dsns["admin"])
