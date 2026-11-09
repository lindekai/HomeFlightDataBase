"""SHA-256-Prüfsummen im Format von ``sha256sum``."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sidecar(path: Path) -> str:
    """Liest die Prüfsumme aus ``<datei>.sha256``; ``ValueError`` bei ungültigem Inhalt."""
    digest = path.read_text(encoding="ascii").split(maxsplit=1)[0].lower()
    if not _HEX64.match(digest):
        raise ValueError(f"ungültige Prüfsummendatei: {path}")
    return digest


def verify(data: Path, sidecar: Path) -> bool:
    try:
        return sha256_file(data) == read_sidecar(sidecar)
    except (OSError, ValueError, IndexError):
        return False
