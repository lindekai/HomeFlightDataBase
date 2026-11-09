from pathlib import Path

import pytest
from recorder.config import Config


def test_from_env_defaults():
    cfg = Config.from_env({"RECEIVER_ID": "TEST", "READSB_URL": "http://x/data/aircraft.json"})
    assert cfg.data_dir == Path("/data")
    assert cfg.rotate_seconds == 3600
    assert cfg.synthetic is False


def test_from_env_overrides():
    cfg = Config.from_env(
        {
            "RECEIVER_ID": "TEST",
            "READSB_URL": "http://x",
            "RECORDER_DATA_DIR": "/tmp/d",
            "RECORDER_ROTATE_SECONDS": "10",
            "RECEIVER_RETENTION_DAYS": "2",
            "RECORDER_SYNTHETIC": "1",
        }
    )
    assert (cfg.data_dir, cfg.rotate_seconds, cfg.retention_days, cfg.synthetic) == (
        Path("/tmp/d"),
        10,
        2.0,
        True,
    )


def test_receiver_id_required():
    with pytest.raises(KeyError):
        Config.from_env({"READSB_URL": "http://x"})
