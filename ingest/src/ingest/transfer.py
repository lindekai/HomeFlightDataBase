"""rsync-Befehle für Abholung und Quittierung (Gegenstelle: rrsync auf dem Pi)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ingest.config import Config


class TransferError(Exception):
    pass


def _ssh(cfg: Config, key: Path) -> str:
    return (
        f"ssh -i {key} -o BatchMode=yes -o ConnectTimeout=15"
        f" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={cfg.known_hosts}"
    )


def _remote(cfg: Config) -> str:
    # Mit rrsync ist das erlaubte Verzeichnis die Wurzel; daher leerer Pfad.
    return f"{cfg.receiver_user}@{cfg.receiver_host}:"


def pull_command(cfg: Config) -> list[str]:
    return [
        "rsync",
        "-rt",
        "--prune-empty-dirs",
        f"--compare-dest={cfg.archive_dir}/",
        "--include=*/",
        "--include=*.ndjson.gz",
        "--include=*.sha256",
        "--exclude=*",
        "-e",
        _ssh(cfg, cfg.ssh_key_read),
        _remote(cfg),
        f"{cfg.staging_dir}/",
    ]


def push_acks_command(cfg: Config) -> list[str]:
    return [
        "rsync",
        "-rt",
        "--perms",
        "--chmod=D2775,F0664",
        "-e",
        _ssh(cfg, cfg.ssh_key_ack),
        f"{cfg.ack_dir}/",
        _remote(cfg),
    ]


def run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise TransferError((getattr(e, "stderr", "") or str(e)).strip()) from e
