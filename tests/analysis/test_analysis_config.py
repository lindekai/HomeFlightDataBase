from pathlib import Path

from analysis.config import Config


def test_from_env_defaults():
    cfg = Config.from_env(
        {"ANALYSIS_DB_DSN": "postgresql://x", "ANALYSIS_BER_LAT": "49.5", "ANALYSIS_BER_LON": "8.5"}
    )
    assert (cfg.ber_lat, cfg.ber_lon) == (49.5, 8.5)
    assert cfg.zones_file is None
    assert (cfg.flight_gap_s, cfg.settle_s, cfg.default_relevance_ft) == (600, 120, 10000)


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
