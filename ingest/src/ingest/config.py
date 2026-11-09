"""Konfiguration aus Umgebungsvariablen."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    admin_dsn: str
    ingest_dsn: str
    receiver_host: str
    receiver_user: str
    ssh_key_read: Path
    ssh_key_ack: Path
    work_dir: Path
    archive_dir: Path
    migrations_dir: Path
    interval_s: int = 300
    environment: str = "production"

    @property
    def staging_dir(self) -> Path:
        return self.work_dir / "staging"

    @property
    def ack_dir(self) -> Path:
        return self.work_dir / "acks"

    @property
    def quarantine_dir(self) -> Path:
        return self.work_dir / "quarantine"

    @property
    def heartbeat_file(self) -> Path:
        return self.work_dir / "heartbeat"

    @property
    def known_hosts(self) -> Path:
        return self.work_dir / "known_hosts"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        return cls(
            admin_dsn=env["INGEST_ADMIN_DSN"],
            ingest_dsn=env["INGEST_DB_DSN"],
            receiver_host=env["RECEIVER_HOST"],
            receiver_user=env["RECEIVER_SSH_USER"],
            ssh_key_read=Path(env["INGEST_SSH_KEY_READ"]),
            ssh_key_ack=Path(env["INGEST_SSH_KEY_ACK"]),
            work_dir=Path(env.get("INGEST_WORK_DIR", "/work")),
            archive_dir=Path(env.get("RAW_ARCHIVE_DIR", "/archive")),
            migrations_dir=Path(env.get("INGEST_MIGRATIONS_DIR", "/app/migrations")),
            interval_s=int(env.get("INGEST_INTERVAL_S", "300")),
            environment=env.get("FLIGHTDB_ENV", "production"),
        )
