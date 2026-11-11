from pathlib import Path

from analysis.config import Config


def test_from_env_defaults():
    cfg = Config.from_env(
        {"ANALYSIS_DB_DSN": "postgresql://x", "ANALYSIS_BER_LAT": "49.5", "ANALYSIS_BER_LON": "8.5"}
    )
    assert (cfg.ber_lat, cfg.ber_lon) == (49.5, 8.5)
    assert cfg.zones_file is None
    assert (cfg.flight_gap_s, cfg.settle_s, cfg.default_relevance_ft) == (600, 120, 10000)
    assert cfg.procedures_file is None
    assert (cfg.corridor_m, cfg.approach_tol, cfg.route_max_alt_ft) == (1852.0, 1852.0, None)


def test_from_env_overrides_and_params():
    cfg = Config.from_env(
        {
            "ANALYSIS_DB_DSN": "postgresql://x",
            "ANALYSIS_BER_LAT": "49.5",
            "ANALYSIS_BER_LON": "8.5",
            "ANALYSIS_ZONES_FILE": "/zones/geofences.geojson",
            "ANALYSIS_FLIGHT_GAP_S": "30",
            "ANALYSIS_VRATE_FPM": "500",
        }
    )
    assert cfg.zones_file == Path("/zones/geofences.geojson")
    params = cfg.params()
    assert params["flight_gap_s"] == 30 and params["vrate_fpm"] == 500.0
    assert "db_dsn" not in params


def test_route_parameters():
    cfg = Config.from_env(
        {
            "ANALYSIS_DB_DSN": "postgresql://x",
            "ANALYSIS_BER_LAT": "49.5",
            "ANALYSIS_BER_LON": "8.5",
            "ANALYSIS_PROCEDURES_FILE": "/zones/procedures.yaml",
            "ANALYSIS_CORRIDOR_M": "1000",
            "ANALYSIS_ROUTE_MAX_ALT_FT": "6000",
            "ANALYSIS_APPROACH_TOL_M": "",
        }
    )
    assert (cfg.corridor_m, cfg.approach_tol, cfg.route_max_alt_ft) == (1000.0, 1000.0, 6000)
    params = cfg.params()
    assert params["procedures_file"] == "/zones/procedures.yaml"
    assert (params["approach_tol"], params["direction_min_share"]) == (1000.0, 0.8)
    assert {"role_near_m", "assign_ratio", "corridor_min_s", "review_max_gap_s"} <= set(params)
