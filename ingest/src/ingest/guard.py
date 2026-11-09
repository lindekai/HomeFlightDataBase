"""Schutzsperre: synthetische Testdaten dürfen nie in die Produktivdatenbank."""

from __future__ import annotations

from ingest.parse import ParsedFile

TEST_RECEIVER_ID = "TEST"


class SyntheticDataRejected(Exception):
    pass


def check(parsed: ParsedFile, environment: str) -> None:
    if environment != "production":
        return
    if parsed.synthetic or parsed.receiver_id == TEST_RECEIVER_ID:
        raise SyntheticDataRejected("synthetische Testdaten in Produktionsumgebung abgelehnt")
