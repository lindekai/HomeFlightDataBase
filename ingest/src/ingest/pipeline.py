"""Verarbeitung abgeholter Rohdateien: prüfen, archivieren, laden, quittieren."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from ingest import __version__, checksum, db, guard, transfer
from ingest.config import Config
from ingest.parse import InconsistentFile, ParsedFile, parse_file

log = logging.getLogger("ingest")

PARTIAL_MARK = ".partial."


@dataclass(frozen=True)
class FileResult:
    rel: str
    status: str  # ingested | skipped | quarantined | failed
    positions: int = 0
    message: str = ""


class ArchiveConflict(Exception):
    pass


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def file_start(name: str) -> datetime:
    """Beginn einer Rohdatei aus ihrem Namen, z. B. ``20261109T140000Z.ndjson.gz``."""
    return datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _quarantine(cfg: Config, staged: Path, rel: str, reason: str) -> FileResult:
    target = cfg.quarantine_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(staged, target)
    if _sidecar(staged).exists():
        shutil.move(_sidecar(staged), _sidecar(target))
    log.warning("Datei in Quarantäne", extra={"file": rel, "reason": reason})
    return FileResult(rel, "quarantined", message=reason)


def _archive(staged: Path, target: Path, digest: str) -> None:
    """Kopiert Datei und Prüfsumme unverändert ins Archiv, prüft die Kopie, löscht das Original."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if checksum.sha256_file(target) != digest:
            raise ArchiveConflict(f"abweichende Datei im Archiv: {target}")
    else:
        tmp = target.with_name(f".{target.name}.tmp")
        shutil.copyfile(staged, tmp)
        if checksum.sha256_file(tmp) != digest:
            tmp.unlink()
            raise ArchiveConflict(f"Kopie fehlerhaft: {target}")
        os.replace(tmp, target)
    shutil.copyfile(_sidecar(staged), _sidecar(target))
    staged.unlink()
    _sidecar(staged).unlink()


def _write_ack(cfg: Config, rel: str, digest: str) -> None:
    ack = cfg.ack_dir / (rel + ".ack")
    ack.parent.mkdir(parents=True, exist_ok=True)
    ack.write_text(digest + "\n", encoding="ascii")


def _load(
    cfg: Config,
    admin: psycopg.Connection,
    conn: psycopg.Connection,
    raw_id: int,
    rel: str,
    digest: str,
    parsed: ParsedFile,
    ack: bool,
) -> FileResult:
    try:
        if parsed.positions:
            db.ensure_partitions(
                admin, min(p.ts for p in parsed.positions), max(p.ts for p in parsed.positions)
            )
        inserted = db.load_parsed(conn, raw_id, parsed)
    except psycopg.OperationalError:
        raise
    except psycopg.Error as e:
        db.mark_failed(conn, raw_id, str(e))
        log.error("Laden fehlgeschlagen", extra={"file": rel, "error": str(e)})
        return FileResult(rel, "failed", message=str(e))
    if ack:
        _write_ack(cfg, rel, digest)
    log.info("Datei verarbeitet", extra={"file": rel, "positions": inserted})
    return FileResult(rel, "ingested", positions=inserted)


def process_file(
    cfg: Config, admin: psycopg.Connection, conn: psycopg.Connection, staged: Path
) -> FileResult:
    rel = staged.relative_to(cfg.staging_dir).as_posix()
    if not _sidecar(staged).exists():
        return FileResult(rel, "skipped", message="Prüfsummendatei fehlt")
    if not checksum.verify(staged, _sidecar(staged)):
        return _quarantine(cfg, staged, rel, "Prüfsumme stimmt nicht")
    digest = checksum.read_sidecar(_sidecar(staged))

    try:
        parsed = parse_file(staged)
    except (OSError, EOFError, InconsistentFile) as e:
        return _quarantine(cfg, staged, rel, f"nicht lesbar: {e}")
    if parsed.receiver_id != rel.split("/", 1)[0]:
        return _quarantine(cfg, staged, rel, "receiver_id passt nicht zum Pfad")
    try:
        guard.check(parsed, cfg.environment)
    except guard.SyntheticDataRejected as e:
        return _quarantine(cfg, staged, rel, str(e))

    db.ensure_receiver(conn, parsed.receiver_id)
    try:
        raw_id, status = db.register_raw_file(
            conn,
            receiver_id=parsed.receiver_id,
            path=rel,
            sha256=digest,
            size_bytes=staged.stat().st_size,
            partial=PARTIAL_MARK in staged.name,
            version=__version__,
        )
    except psycopg.errors.UniqueViolation:
        return _quarantine(cfg, staged, rel, "gleicher Pfad mit anderer Prüfsumme bereits erfasst")

    try:
        _archive(staged, cfg.archive_dir / rel, digest)
    except ArchiveConflict as e:
        db.mark_failed(conn, raw_id, str(e))
        return _quarantine(cfg, staged, rel, str(e))

    if status == "ingested":
        _write_ack(cfg, rel, digest)
        return FileResult(rel, "skipped", message="bereits verarbeitet")
    return _load(cfg, admin, conn, raw_id, rel, digest, parsed, ack=True)


def _retry_pending(
    cfg: Config, admin: psycopg.Connection, conn: psycopg.Connection
) -> list[FileResult]:
    results = []
    for raw_id, rel, digest in db.pending_files(conn):
        path = cfg.archive_dir / rel
        if not path.exists() or checksum.sha256_file(path) != digest:
            log.error("Archivdatei fehlt oder Prüfsumme abweichend", extra={"file": rel})
            continue
        results.append(_load(cfg, admin, conn, raw_id, rel, digest, parse_file(path), ack=True))
    return results


def _prepare_dirs(cfg: Config) -> None:
    for d in (cfg.staging_dir, cfg.ack_dir, cfg.quarantine_dir, cfg.archive_dir):
        d.mkdir(parents=True, exist_ok=True)


def run_once(cfg: Config, pull: bool = True) -> list[FileResult]:
    _prepare_dirs(cfg)
    if pull:
        try:
            transfer.run(transfer.pull_command(cfg))
        except transfer.TransferError as e:
            log.warning("Abholung fehlgeschlagen", extra={"error": str(e)})

    with (
        psycopg.connect(cfg.admin_dsn, autocommit=True) as admin,
        psycopg.connect(cfg.ingest_dsn, autocommit=True) as conn,
    ):
        now = datetime.now(UTC)
        db.ensure_partitions(admin, now, now + timedelta(days=32))
        results = _retry_pending(cfg, admin, conn)
        for staged in sorted(cfg.staging_dir.rglob("*.ndjson.gz")):
            if not staged.name.startswith("."):
                results.append(process_file(cfg, admin, conn, staged))

    if pull and any(cfg.ack_dir.rglob("*.ack")):
        try:
            transfer.run(transfer.push_acks_command(cfg))
            shutil.rmtree(cfg.ack_dir)
            cfg.ack_dir.mkdir()
        except transfer.TransferError as e:
            log.warning("Quittierung fehlgeschlagen", extra={"error": str(e)})

    cfg.heartbeat_file.touch()
    return results


def rebuild(cfg: Config, start: datetime, end: datetime) -> list[FileResult]:
    """Lädt Archivdateien mit Beginn in [start, end) neu. Das Archiv wird nicht verändert."""
    _prepare_dirs(cfg)
    results = []
    with (
        psycopg.connect(cfg.admin_dsn, autocommit=True) as admin,
        psycopg.connect(cfg.ingest_dsn, autocommit=True) as conn,
    ):
        for path in sorted(cfg.archive_dir.rglob("*.ndjson.gz")):
            if path.name.startswith(".") or not start <= file_start(path.name) < end:
                continue
            rel = path.relative_to(cfg.archive_dir).as_posix()
            digest = checksum.read_sidecar(_sidecar(path))
            if checksum.sha256_file(path) != digest:
                results.append(FileResult(rel, "failed", message="Archiv-Prüfsumme stimmt nicht"))
                continue
            parsed = parse_file(path)
            raw_id = db.find_raw_file(conn, digest)
            if raw_id is None:
                db.ensure_receiver(conn, parsed.receiver_id)
                raw_id, _ = db.register_raw_file(
                    conn,
                    receiver_id=parsed.receiver_id,
                    path=rel,
                    sha256=digest,
                    size_bytes=path.stat().st_size,
                    partial=PARTIAL_MARK in path.name,
                    version=__version__,
                )
            else:
                db.delete_file_data(conn, raw_id)
            results.append(_load(cfg, admin, conn, raw_id, rel, digest, parsed, ack=False))
    return results
