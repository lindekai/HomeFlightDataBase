import pytest

from ingest.guard import SyntheticDataRejected, check
from ingest.parse import ParsedFile


def test_production_rejects_synthetic():
    with pytest.raises(SyntheticDataRejected):
        check(ParsedFile(receiver_id="RX1", synthetic=True), "production")
    with pytest.raises(SyntheticDataRejected):
        check(ParsedFile(receiver_id="TEST"), "production")


def test_production_accepts_real_and_test_env_accepts_all():
    check(ParsedFile(receiver_id="RX1"), "production")
    check(ParsedFile(receiver_id="TEST", synthetic=True), "test")
