import json
from pathlib import Path

import build_dashboards
import check_dashboards

ROOT = Path(__file__).resolve().parents[2]


def test_generated_files_are_current():
    for name, dashboard in build_dashboards.build().items():
        on_disk = json.loads((ROOT / "dashboard" / "dashboards" / name).read_text("utf-8"))
        assert on_disk == dashboard, f"{name} veraltet – python dashboard/build_dashboards.py"


def test_dashboards_have_unique_uids_and_panel_ids():
    dashboards = build_dashboards.build().values()
    assert len({d["uid"] for d in dashboards}) == 4
    for d in dashboards:
        ids = [p["id"] for p in d["panels"]]
        assert len(ids) == len(set(ids))


def test_repo_dashboards_contain_no_locations():
    files = sorted((ROOT / "dashboard" / "dashboards").glob("*.json"))
    assert files and check_dashboards.main([str(f) for f in files]) == 0


def test_checker_finds_map_center_and_zoom():
    bad = {
        "panels": [
            {
                "type": "geomap",
                "options": {"view": {"id": "coords", "lat": 45.0, "lon": -30.0, "zoom": 11}},
            }
        ]
    }
    found = check_dashboards.problems(bad)
    assert len(found) == 4  # Ansicht nicht 'fit', lat, lon, zoom


def test_checker_accepts_field_names():
    ok = {
        "type": "geomap",
        "options": {
            "view": {"id": "fit"},
            "layers": [
                {"location": {"mode": "coords", "latitude": "latitude", "longitude": "longitude"}}
            ],
        },
    }
    assert check_dashboards.problems(ok) == []
