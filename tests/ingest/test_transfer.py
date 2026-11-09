from pathlib import Path

from ingest.config import Config
from ingest.transfer import pull_command, push_acks_command


def cfg():
    return Config(
        admin_dsn="",
        ingest_dsn="",
        receiver_host="receiver",
        receiver_user="flightdb-sync",
        ssh_key_read=Path("/keys/read"),
        ssh_key_ack=Path("/keys/ack"),
        work_dir=Path("/work"),
        archive_dir=Path("/archive"),
        migrations_dir=Path("/m"),
    )


def test_pull_command():
    cmd = pull_command(cfg())
    assert cmd[0] == "rsync"
    assert "--compare-dest=/archive/" in cmd
    assert "--include=*.ndjson.gz" in cmd and "--include=*.sha256" in cmd and "--exclude=*" in cmd
    ssh = cmd[cmd.index("-e") + 1]
    assert "-i /keys/read" in ssh and "StrictHostKeyChecking=accept-new" in ssh
    assert cmd[-2:] == ["flightdb-sync@receiver:", "/work/staging/"]


def test_push_acks_command():
    cmd = push_acks_command(cfg())
    assert "--chmod=D2775,F0664" in cmd
    assert "-i /keys/ack" in cmd[cmd.index("-e") + 1]
    assert cmd[-2:] == ["/work/acks/", "flightdb-sync@receiver:"]
