# Meilenstein 2 – Empfang und Speicherung: Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rohdaten des ADS-B-Empfängers verlustarm aufzeichnen, unverändert mit Prüfsumme archivieren und normalisiert in PostGIS laden – vollständig mit synthetischen Daten testbar, bevor die Hardware da ist.

**Architecture:** Auf dem Pi schreibt `recorder` jede Sekunde die `aircraft.json` von readsb unverändert in rotierende NDJSON-Dateien und schließt sie mit SHA-256 ab. Auf dem NAS holt `ingest` abgeschlossene Dateien per rsync/rrsync ab, prüft, archiviert, lädt sie per `COPY` in eine monatlich partitionierte PostGIS-Tabelle und quittiert sie. Spezifikation: `docs/superpowers/specs/2026-11-09-meilenstein-2-empfang-speicherung-design.md`.

**Tech Stack:** Python 3.12 (recorder: nur Standardbibliothek; ingest: psycopg 3), PostgreSQL 16 + PostGIS 3.4 (`postgis/postgis:16-3.4`), Docker Compose, rsync/rrsync über SSH, pytest, ruff, GitHub Actions.

## Global Constraints

- **Öffentliches Repo:** keine Koordinaten, Adressen, Ortsnamen des Wohnumfelds, Hostnamen, IPs, Seriennummern, Zugangsdaten oder Screenshots committen. Echte Werte nur in gitignorierten `.env`-Dateien bzw. `config/local/`.
- **Commits:** Autor ist ausschließlich der Repo-Inhaber (noreply-Adresse). **Keine** `Co-Authored-By`-Zeilen, kein „Generated with Claude Code“. Die Hooks aus Task 1 erzwingen das.
- **Keine erfundenen Flugdaten:** Testdaten sind synthetisch – Empfänger-ID `TEST`, ICAO24 mit Präfix `ff`, Feld `"synthetic": true`, Koordinaten frei gewählt (50.0 / 10.0).
- Rohdaten werden **nie verändert**; die Datenbank ist daraus jederzeit neu aufbaubar.
- Einheiten wie readsb: Fuß, Knoten, ft/min; Zeiten in UTC (`timestamptz`).
- Image-Versionen fest angeben, nie `latest` ohne Digest.
- Keine Änderung an bestehenden produktiven NAS-Containern (n8n und dessen Postgres).
- Python-Stil: ruff (`line-length = 100`), `ruff format`; Kommentare und Docstrings auf Deutsch, knapp. Meldet `ruff check` Import-Reihenfolge oder Zeilenlänge im Plan-Code: `ruff check --fix . && ruff format .` – inhaltlich nichts ändern.
- Vor jedem Commit: `git diff --cached` kurz auf sensible Inhalte sichten (der Hook prüft zusätzlich).

## Dateistruktur

```text
pyproject.toml                       pytest-/ruff-Konfiguration (kein installierbares Paket)
requirements-dev.txt                 Test- und Lint-Abhängigkeiten
scripts/
  check-sensitive.sh                 pre-commit: sensible Muster + noreply-Adresse
  check-commit-msg.sh                commit-msg: keine Claude-Attribution
  install-hooks.sh                   verlinkt beide Hooks
.github/workflows/ci.yml             Lint, Unit-, DB- und E2E-Tests
receiver/
  docker-compose.yml                 ultrafeeder, Feeder, recorder, autoheal
  .env.example
  recorder/
    Dockerfile
    src/recorder/
      __init__.py                    Version
      __main__.py                    Einstiegspunkt, Signale
      config.py                      Konfiguration aus Umgebungsvariablen
      timeutil.py                    utcnow(), iso()
      logjson.py                     JSON-Logging
      files.py                       Dateinamen, Abschluss, Wiederherstellung
      writer.py                      RotatingWriter
      gaps.py                        GapDetector
      cleanup.py                     Aufräumen, freier Speicher
      source.py                      aircraft.json abrufen
      clock.py                       SNTP-Abweichung
      main.py                        Recorder (start/tick/stop), run()
      health.py                      Healthcheck
ingest/
  Dockerfile
  src/ingest/
    __init__.py                      Version
    __main__.py                      → cli.main()
    config.py                        Konfiguration
    logjson.py                       JSON-Logging
    checksum.py                      SHA-256, Sidecar
    parse.py                         Rohdatei → ParsedFile
    guard.py                         Sperre für synthetische Daten
    db.py                            Migrationen, Partitionen, Laden
    transfer.py                      rsync-Befehle
    pipeline.py                      process_file, run_once, rebuild
    cli.py                           run | once | migrate | rebuild | health
database/
  migrations/001_erfassung.sql
  init/10-roles.sh
  backup/backup.sh
nas/
  docker-compose.yml                 postgis, ingest, backup
  .env.example
tests/
  conftest.py                        DB-Fixture
  compose.test.yml                   lokale Test-Datenbank
  fixtures/synthetic/
    __init__.py
    generator.py                     synthetische aircraft.json
    rawfiles.py                      synthetische Rohdateien
    serve.py                         readsb-Attrappe (HTTP)
  recorder/ …                        Unit-Tests recorder
  ingest/ …                          Unit-Tests ingest
  db/ …                              Integrationstests (Marker db)
  e2e/
    compose.yml
    receiver-ssh/Dockerfile, entrypoint.sh
    test_e2e.py                      (Marker e2e)
docs/
  deployment-nas.md
  deployment-receiver.md
  data-model.md
```

Die bestehende Datei `.env.example` im Wurzelverzeichnis wird in Task 10 durch `nas/.env.example` und `receiver/.env.example` ersetzt.

---

### Task 1: Werkzeuge und Schutz-Hooks

**Files:**
- Create: `pyproject.toml`, `requirements-dev.txt`, `scripts/check-sensitive.sh`, `scripts/check-commit-msg.sh`, `scripts/install-hooks.sh`
- Create (lokal, **nicht** committen): `config/local/sensitive-patterns.txt`

**Interfaces:**
- Produces: `pytest`-Konfiguration mit `pythonpath = receiver/recorder/src, ingest/src, tests/fixtures`; Marker `db` und `e2e`; aktive Git-Hooks.

- [ ] **Step 1: Konfigurationsdateien anlegen**

`pyproject.toml`:

```toml
# Nur Werkzeugkonfiguration; recorder und ingest werden als Container gebaut.

[tool.pytest.ini_options]
pythonpath = ["receiver/recorder/src", "ingest/src", "tests/fixtures"]
testpaths = ["tests"]
addopts = "-m 'not e2e'"
markers = [
    "db: benötigt eine PostGIS-Testdatenbank (TEST_ADMIN_DSN)",
    "e2e: End-to-End-Test mit Docker Compose",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

`requirements-dev.txt`:

```text
pytest==8.3.3
ruff==0.7.4
psycopg[binary]==3.2.3
```

- [ ] **Step 2: Hooks schreiben**

`scripts/check-sensitive.sh`:

```bash
#!/usr/bin/env bash
# pre-commit: verhindert sensible Inhalte im öffentlichen Repo.
# Muster stehen lokal in config/local/sensitive-patterns.txt (gitignored), eine Regex pro Zeile.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
patterns="$root/config/local/sensitive-patterns.txt"
fail=0

email=$(git config user.email || true)
if [[ "$email" != *@users.noreply.github.com ]]; then
  echo "FEHLER: git user.email ist keine noreply-Adresse." >&2
  fail=1
fi

if [[ ! -s "$patterns" ]]; then
  echo "FEHLER: $patterns fehlt oder ist leer." >&2
  exit 1
fi

if git diff --cached -U0 --no-color | grep '^+' | grep -v '^+++' | grep -inEf "$patterns"; then
  echo "FEHLER: sensible Inhalte im Commit (siehe oben)." >&2
  fail=1
fi

if git diff --cached --name-only | grep -iEf "$patterns"; then
  echo "FEHLER: sensibler Dateiname im Commit." >&2
  fail=1
fi

exit $fail
```

`scripts/check-commit-msg.sh`:

```bash
#!/usr/bin/env bash
# commit-msg: keine Attribution an KI-Werkzeuge in Commit-Nachrichten.
set -euo pipefail

if grep -qiE '^co-authored-by:.*(claude|anthropic)|generated with .*claude' "$1"; then
  echo "FEHLER: Commit-Nachricht enthält eine Claude-Attribution." >&2
  exit 1
fi
```

`scripts/install-hooks.sh`:

```bash
#!/usr/bin/env bash
# Verlinkt die Schutz-Hooks in .git/hooks.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
ln -sf ../../scripts/check-sensitive.sh "$root/.git/hooks/pre-commit"
ln -sf ../../scripts/check-commit-msg.sh "$root/.git/hooks/commit-msg"
chmod +x "$root/scripts/"*.sh
echo "Hooks installiert."
```

- [ ] **Step 3: Lokale Musterdatei anlegen und Hooks installieren**

`config/local/sensitive-patterns.txt` lokal anlegen (ist durch `.gitignore` ausgeschlossen). Inhalt: je Zeile ein Begriff als Regex – Ortsnamen aus der Projektübergabe (`writing-block.md`, Abschnitt 7), NAS-Servername, NAS-Seriennummer, Laufwerksmodelle, die private Mail-Adresse, lokale IP-Präfixe (`192\.168\.`), und die eigenen Empfängerkoordinaten, sobald bekannt. **Den Inhalt nicht in Commits, Logs oder Chat wiederholen.**

Run:

```bash
git check-ignore -v config/local/sensitive-patterns.txt
bash scripts/install-hooks.sh
```

Expected: `.gitignore:…:config/local/	config/local/sensitive-patterns.txt` und `Hooks installiert.`

- [ ] **Step 4: Hooks prüfen**

```bash
echo "192.168.1.1" > hooktest.txt && git add hooktest.txt
git commit -m "test" ; echo "exit=$?"
git reset -q hooktest.txt && rm hooktest.txt
printf 'x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n' > /tmp/msg.txt
bash scripts/check-commit-msg.sh /tmp/msg.txt ; echo "exit=$?"
```

Expected: beim Commit `FEHLER: sensible Inhalte im Commit` und `exit=1`; beim Nachrichtentest `FEHLER: …Claude-Attribution` und `exit=1`.

- [ ] **Step 5: Python-Umgebung**

```bash
python3 --version   # erwartet 3.12.x oder neuer
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
ruff --version && pytest --version
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements-dev.txt scripts/
git commit -m "Werkzeuge und Schutz-Hooks gegen sensible Inhalte"
```

---

### Task 2: recorder – Dateien und RotatingWriter, CI

**Files:**
- Create: `receiver/recorder/src/recorder/__init__.py`, `timeutil.py`, `files.py`, `writer.py`
- Create: `tests/recorder/test_files.py`, `tests/recorder/test_writer.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces:
  - `recorder.__version__: str`
  - `recorder.timeutil.utcnow() -> datetime`, `iso(ts: datetime) -> str` (z. B. `2026-11-09T14:00:00.000Z`)
  - `recorder.files`: `CURRENT_SUFFIX=".ndjson"`, `COMPLETE_SUFFIX=".ndjson.gz"`, `PARTIAL_MARK=".partial"`, `file_stem(receiver_id: str, start: datetime) -> Path`, `period_start(ts: datetime, rotate_seconds: int) -> datetime`, `sha256_file(path: Path) -> str`, `finalize(current_file: Path, current_dir: Path, complete_dir: Path, partial: bool = False) -> Path`, `truncate_incomplete_line(path: Path) -> None`, `recover(current_dir: Path, complete_dir: Path) -> list[Path]`, `last_activity(*dirs: Path) -> datetime | None`
  - `recorder.writer.RotatingWriter(receiver_id, current_dir, complete_dir, rotate_seconds)` mit `write(record: dict, ts: datetime) -> Path | None`, `rotate_if_due(ts) -> Path | None`, `close(partial: bool = False) -> Path | None`

- [ ] **Step 1: Failing Tests schreiben**

`tests/recorder/test_files.py`:

```python
import gzip
import os
from datetime import UTC, datetime
from pathlib import Path

from recorder.files import (
    file_stem,
    finalize,
    last_activity,
    period_start,
    recover,
    sha256_file,
    truncate_incomplete_line,
)


def test_file_stem_uses_utc_start():
    start = datetime(2026, 11, 9, 14, 5, 7, tzinfo=UTC)
    assert file_stem("TEST", start) == Path("TEST/2026/11/09/20261109T140507Z")


def test_period_start_aligns_to_rotation():
    ts = datetime(2026, 11, 9, 14, 59, 59, tzinfo=UTC)
    assert period_start(ts, 3600) == datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
    assert period_start(ts, 10) == datetime(2026, 11, 9, 14, 59, 50, tzinfo=UTC)


def test_finalize_compresses_and_writes_sidecar(tmp_path):
    cur, comp = tmp_path / "current", tmp_path / "complete"
    src = cur / "TEST/2026/11/09/20261109T140000Z.ndjson"
    src.parent.mkdir(parents=True)
    src.write_bytes(b'{"a":1}\n')

    target = finalize(src, cur, comp)

    assert target == comp / "TEST/2026/11/09/20261109T140000Z.ndjson.gz"
    assert gzip.decompress(target.read_bytes()) == b'{"a":1}\n'
    sidecar = target.with_name(target.name + ".sha256")
    assert sidecar.read_text() == f"{sha256_file(target)}  {target.name}\n"
    assert not src.exists()


def test_finalize_partial_marks_name(tmp_path):
    cur, comp = tmp_path / "current", tmp_path / "complete"
    src = cur / "TEST/2026/11/09/20261109T140000Z.ndjson"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"{}\n")
    target = finalize(src, cur, comp, partial=True)
    assert target.name == "20261109T140000Z.partial.ndjson.gz"


def test_truncate_incomplete_line(tmp_path):
    p = tmp_path / "f.ndjson"
    p.write_bytes(b'{"a":1}\n{"b":')
    truncate_incomplete_line(p)
    assert p.read_bytes() == b'{"a":1}\n'


def test_truncate_keeps_complete_file_and_empties_single_fragment(tmp_path):
    ok, frag = tmp_path / "ok.ndjson", tmp_path / "frag.ndjson"
    ok.write_bytes(b'{"a":1}\n')
    frag.write_bytes(b'{"a":')
    truncate_incomplete_line(ok)
    truncate_incomplete_line(frag)
    assert ok.read_bytes() == b'{"a":1}\n'
    assert frag.read_bytes() == b""


def test_recover_finalizes_as_partial_and_drops_empty(tmp_path):
    cur, comp = tmp_path / "current", tmp_path / "complete"
    day = cur / "TEST/2026/11/09"
    day.mkdir(parents=True)
    (day / "20261109T140000Z.ndjson").write_bytes(b'{"a":1}\n{"b"')
    (day / "20261109T150000Z.ndjson").write_bytes(b'{"x"')

    recovered = recover(cur, comp)

    assert recovered == [comp / "TEST/2026/11/09/20261109T140000Z.partial.ndjson.gz"]
    assert gzip.decompress(recovered[0].read_bytes()) == b'{"a":1}\n'
    assert list(cur.rglob("*.ndjson")) == []


def test_last_activity_returns_newest_mtime(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "old").write_text("x")
    (b / "new").write_text("y")
    os.utime(a / "old", (1_700_000_000, 1_700_000_000))
    os.utime(b / "new", (1_800_000_000, 1_800_000_000))
    assert last_activity(a, b) == datetime.fromtimestamp(1_800_000_000, tz=UTC)
    assert last_activity(tmp_path / "missing") is None
```

`tests/recorder/test_writer.py`:

```python
import gzip
import json
from datetime import UTC, datetime

from recorder.files import sha256_file
from recorder.writer import RotatingWriter


def ts(h, m, s):
    return datetime(2026, 11, 9, h, m, s, tzinfo=UTC)


def read_gz(path):
    return [json.loads(line) for line in gzip.open(path, "rt").read().splitlines()]


def test_rotation_finalizes_previous_period(tmp_path):
    cur, comp = tmp_path / "current", tmp_path / "complete"
    w = RotatingWriter("TEST", cur, comp, 3600)

    assert w.write({"n": 1}, ts(14, 59, 59)) is None
    done = w.write({"n": 2}, ts(15, 0, 0))

    assert done == comp / "TEST/2026/11/09/20261109T145959Z.ndjson.gz"
    assert read_gz(done) == [{"n": 1}]
    assert done.with_name(done.name + ".sha256").read_text().startswith(sha256_file(done))
    assert list(cur.rglob("*.ndjson")) == [cur / "TEST/2026/11/09/20261109T150000Z.ndjson"]


def test_rotate_if_due_without_write(tmp_path):
    w = RotatingWriter("TEST", tmp_path / "c", tmp_path / "d", 10)
    w.write({"n": 1}, ts(14, 0, 1))
    assert w.rotate_if_due(ts(14, 0, 9)) is None
    assert w.rotate_if_due(ts(14, 0, 10)) is not None


def test_close_partial(tmp_path):
    w = RotatingWriter("TEST", tmp_path / "c", tmp_path / "d", 3600)
    w.write({"n": 1}, ts(14, 10, 0))
    done = w.close(partial=True)
    assert done.name == "20261109T141000Z.partial.ndjson.gz"
    assert w.close() is None
```

- [ ] **Step 2: Tests laufen lassen – müssen fehlschlagen**

Run: `pytest tests/recorder -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'recorder'`

- [ ] **Step 3: Implementierung**

`receiver/recorder/src/recorder/__init__.py`:

```python
"""Rohdatenaufzeichnung der Empfangsstation."""

__version__ = "0.1.0"
```

`receiver/recorder/src/recorder/timeutil.py`:

```python
"""Zeitfunktionen; alle Zeitstempel sind UTC."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    """ISO-8601 mit Millisekunden und ``Z``, z. B. ``2026-11-09T14:00:00.000Z``."""
    return ts.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
```

`receiver/recorder/src/recorder/files.py`:

```python
"""Dateinamen, Abschluss und Wiederherstellung von Rohdatendateien."""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

CURRENT_SUFFIX = ".ndjson"
COMPLETE_SUFFIX = ".ndjson.gz"
PARTIAL_MARK = ".partial"


def file_stem(receiver_id: str, start: datetime) -> Path:
    """Relativer Pfad ohne Endung, z. B. ``TEST/2026/11/09/20261109T140000Z``."""
    s = start.astimezone(UTC)
    return Path(receiver_id, f"{s:%Y}", f"{s:%m}", f"{s:%d}", f"{s:%Y%m%dT%H%M%SZ}")


def period_start(ts: datetime, rotate_seconds: int) -> datetime:
    """Beginn der Rotationsperiode, in der ``ts`` liegt (an der Unix-Epoche ausgerichtet)."""
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - epoch % rotate_seconds, tz=UTC)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fsync(path: Path) -> None:
    with path.open("rb") as f:
        os.fsync(f.fileno())


def finalize(
    current_file: Path, current_dir: Path, complete_dir: Path, partial: bool = False
) -> Path:
    """Komprimiert eine Datei aus ``current/`` und verschiebt sie atomar nach ``complete/``.

    Die ``.sha256`` wird zuletzt angelegt – erst dann gilt die Datei als abholbereit.
    """
    rel = current_file.relative_to(current_dir)
    stem = rel.name.removesuffix(CURRENT_SUFFIX)
    name = stem + (PARTIAL_MARK if partial else "") + COMPLETE_SUFFIX
    target = complete_dir / rel.parent / name
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp = target.with_name(f".{name}.tmp")
    with current_file.open("rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    _fsync(tmp)
    digest = sha256_file(tmp)
    os.replace(tmp, target)

    sidecar_tmp = target.with_name(f".{name}.sha256.tmp")
    sidecar_tmp.write_text(f"{digest}  {name}\n", encoding="ascii")
    _fsync(sidecar_tmp)
    os.replace(sidecar_tmp, target.with_name(name + ".sha256"))

    current_file.unlink()
    return target


def truncate_incomplete_line(path: Path) -> None:
    """Schneidet eine unvollständige letzte Zeile ab (nach Absturz oder Stromausfall)."""
    with path.open("r+b") as f:
        pos = f.seek(0, os.SEEK_END)
        while pos > 0:
            step = min(65536, pos)
            pos -= step
            f.seek(pos)
            idx = f.read(step).rfind(b"\n")
            if idx != -1:
                f.truncate(pos + idx + 1)
                return
        f.truncate(0)


def recover(current_dir: Path, complete_dir: Path) -> list[Path]:
    """Schließt beim Start liegengebliebene Dateien als ``.partial`` ab."""
    recovered = []
    for path in sorted(current_dir.rglob(f"*{CURRENT_SUFFIX}")):
        truncate_incomplete_line(path)
        if path.stat().st_size == 0:
            path.unlink()
            continue
        recovered.append(finalize(path, current_dir, complete_dir, partial=True))
    return recovered


def last_activity(*dirs: Path) -> datetime | None:
    """Jüngste Dateiänderung – Näherung für das Ende der letzten Aufzeichnung."""
    latest = max(
        (p.stat().st_mtime for d in dirs if d.exists() for p in d.rglob("*") if p.is_file()),
        default=None,
    )
    return None if latest is None else datetime.fromtimestamp(latest, tz=UTC)
```

`receiver/recorder/src/recorder/writer.py`:

```python
"""Zeilenweises Schreiben in rotierende Rohdatendateien."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from recorder.files import CURRENT_SUFFIX, file_stem, finalize, period_start


class RotatingWriter:
    def __init__(
        self, receiver_id: str, current_dir: Path, complete_dir: Path, rotate_seconds: int
    ) -> None:
        self._receiver_id = receiver_id
        self._current_dir = current_dir
        self._complete_dir = complete_dir
        self._rotate_seconds = rotate_seconds
        self._fh: BinaryIO | None = None
        self._path: Path | None = None
        self._period: datetime | None = None

    def write(self, record: dict, ts: datetime) -> Path | None:
        """Hängt ``record`` als JSON-Zeile an; gibt eine dabei abgeschlossene Datei zurück."""
        finished = self.rotate_if_due(ts)
        if self._fh is None:
            stem = file_stem(self._receiver_id, ts)
            self._path = self._current_dir / stem.with_name(stem.name + CURRENT_SUFFIX)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("ab")
            self._period = period_start(ts, self._rotate_seconds)
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        self._fh.write(line.encode("utf-8"))
        self._fh.flush()
        return finished

    def rotate_if_due(self, ts: datetime) -> Path | None:
        if self._fh is not None and period_start(ts, self._rotate_seconds) != self._period:
            return self.close()
        return None

    def close(self, partial: bool = False) -> Path | None:
        if self._fh is None:
            return None
        os.fsync(self._fh.fileno())
        self._fh.close()
        path = self._path
        self._fh = self._path = self._period = None
        return finalize(path, self._current_dir, self._complete_dir, partial=partial)
```

- [ ] **Step 4: Tests laufen lassen – müssen bestehen**

Run: `pytest tests/recorder -v && ruff check . && ruff format --check .`
Expected: alle Tests PASS, ruff ohne Befunde (sonst `ruff format .` ausführen).

- [ ] **Step 5: CI-Workflow anlegen**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-24.04
    services:
      postgis:
        image: postgis/postgis:16-3.4
        env:
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 20
    env:
      TEST_ADMIN_DSN: postgresql://postgres:test@localhost:5432/postgres
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements-dev.txt
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest -v
```

(Der E2E-Job wird in Task 12 ergänzt.)

- [ ] **Step 6: Commit**

```bash
git add receiver/recorder/src tests/recorder .github/workflows/ci.yml
git commit -m "recorder: rotierende Rohdatendateien mit Prüfsumme; CI"
```

---

### Task 3: recorder – Lückenerkennung

**Files:**
- Create: `receiver/recorder/src/recorder/gaps.py`
- Test: `tests/recorder/test_gaps.py`

**Interfaces:**
- Consumes: `recorder.timeutil.iso`
- Produces: `recorder.gaps.GapDetector(max_age_s: float)` mit
  - `observe(now: datetime, data_ts: datetime | None) -> dict | None` – liefert `{"from": str, "to": str, "reason": "no_data" | "stale_data"}`, sobald eine Lücke endet
  - `flush(now: datetime) -> dict | None` – schließt eine offene Lücke (beim Beenden)
  - Eigenschaft `in_gap: bool`

- [ ] **Step 1: Failing Test schreiben**

`tests/recorder/test_gaps.py`:

```python
from datetime import UTC, datetime, timedelta

from recorder.gaps import GapDetector

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)


def at(s):
    return T0 + timedelta(seconds=s)


def test_no_gap_while_fresh():
    g = GapDetector(5)
    assert g.observe(at(0), at(0)) is None
    assert g.observe(at(1), at(1)) is None
    assert not g.in_gap


def test_gap_from_last_good_until_recovery():
    g = GapDetector(5)
    g.observe(at(0), at(0))
    assert g.observe(at(1), None) is None
    assert g.in_gap
    assert g.observe(at(2), None) is None
    gap = g.observe(at(3), at(3))
    assert gap == {
        "from": "2026-11-09T14:00:00.000Z",
        "to": "2026-11-09T14:00:03.000Z",
        "reason": "no_data",
    }
    assert not g.in_gap


def test_stale_data_counts_as_gap():
    g = GapDetector(5)
    g.observe(at(0), at(0))
    assert g.observe(at(10), at(4)) is None
    assert g.observe(at(11), at(11))["reason"] == "stale_data"


def test_flush_closes_open_gap():
    g = GapDetector(5)
    g.observe(at(0), at(0))
    g.observe(at(1), None)
    assert g.flush(at(7))["to"] == "2026-11-09T14:00:07.000Z"
    assert g.flush(at(8)) is None
```

- [ ] **Step 2: Test laufen lassen – muss fehlschlagen**

Run: `pytest tests/recorder/test_gaps.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'recorder.gaps'`

- [ ] **Step 3: Implementierung**

`receiver/recorder/src/recorder/gaps.py`:

```python
"""Erkennung von Zeiträumen ohne frische readsb-Daten."""

from __future__ import annotations

from datetime import datetime

from recorder.timeutil import iso


class GapDetector:
    """Meldet eine Lücke, sobald wieder frische Daten kommen oder beim Beenden."""

    def __init__(self, max_age_s: float) -> None:
        self._max_age_s = max_age_s
        self._last_good: datetime | None = None
        self._gap_start: datetime | None = None
        self._reason = ""

    @property
    def in_gap(self) -> bool:
        return self._gap_start is not None

    def observe(self, now: datetime, data_ts: datetime | None) -> dict | None:
        fresh = data_ts is not None and (now - data_ts).total_seconds() <= self._max_age_s
        if not fresh:
            if self._gap_start is None:
                self._gap_start = self._last_good or now
                self._reason = "no_data" if data_ts is None else "stale_data"
            return None
        gap = self.flush(now)
        self._last_good = now
        return gap

    def flush(self, now: datetime) -> dict | None:
        if self._gap_start is None:
            return None
        gap = {"from": iso(self._gap_start), "to": iso(now), "reason": self._reason}
        self._gap_start = None
        return gap
```

- [ ] **Step 4: Test laufen lassen – muss bestehen**

Run: `pytest tests/recorder/test_gaps.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add receiver/recorder/src/recorder/gaps.py tests/recorder/test_gaps.py
git commit -m "recorder: Erkennung von Empfangslücken"
```

---

### Task 4: recorder – Aufräumen und freier Speicher

**Files:**
- Create: `receiver/recorder/src/recorder/cleanup.py`
- Test: `tests/recorder/test_cleanup.py`

**Interfaces:**
- Consumes: `recorder.files.COMPLETE_SUFFIX`
- Produces: `recorder.cleanup.cleanup(complete_dir: Path, acked_dir: Path, retention_days: float, now: datetime) -> list[Path]` (gelöschte relative Pfade), `free_space(path: Path) -> tuple[int, float]` (freie Bytes, Anteil frei)

- [ ] **Step 1: Failing Test schreiben**

`tests/recorder/test_cleanup.py`:

```python
import os
from datetime import UTC, datetime
from pathlib import Path

from recorder.cleanup import cleanup, free_space

NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
DAY = 86400


def make(complete, acked, name, age_days, ack=True):
    gz = complete / "TEST/2026/11/09" / name
    gz.parent.mkdir(parents=True, exist_ok=True)
    gz.write_bytes(b"x")
    sidecar = gz.with_name(gz.name + ".sha256")
    sidecar.write_text("x")
    mtime = NOW.timestamp() - age_days * DAY
    os.utime(gz, (mtime, mtime))
    if ack:
        a = acked / "TEST/2026/11/09" / (name + ".ack")
        a.parent.mkdir(parents=True, exist_ok=True)
        a.write_text("x")
    return gz


def test_deletes_only_acked_and_old(tmp_path):
    complete, acked = tmp_path / "complete", tmp_path / "acked"
    old_acked = make(complete, acked, "20261109T100000Z.ndjson.gz", 8)
    old_unacked = make(complete, acked, "20261109T110000Z.ndjson.gz", 8, ack=False)
    young_acked = make(complete, acked, "20261109T120000Z.ndjson.gz", 1)

    deleted = cleanup(complete, acked, 7, NOW)

    assert deleted == [Path("TEST/2026/11/09/20261109T100000Z.ndjson.gz")]
    assert not old_acked.exists()
    assert not old_acked.with_name(old_acked.name + ".sha256").exists()
    assert not (acked / "TEST/2026/11/09/20261109T100000Z.ndjson.gz.ack").exists()
    assert old_unacked.exists()
    assert young_acked.exists()


def test_removes_orphan_acks_after_retention(tmp_path):
    complete, acked = tmp_path / "complete", tmp_path / "acked"
    complete.mkdir()
    orphan_old = acked / "TEST/2026/11/01/20261101T000000Z.ndjson.gz.ack"
    orphan_new = acked / "TEST/2026/11/19/20261119T000000Z.ndjson.gz.ack"
    for p, age in ((orphan_old, 8), (orphan_new, 1)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        os.utime(p, (NOW.timestamp() - age * DAY,) * 2)

    cleanup(complete, acked, 7, NOW)

    assert not orphan_old.exists()
    assert orphan_new.exists()


def test_free_space(tmp_path):
    free, ratio = free_space(tmp_path)
    assert free > 0
    assert 0 < ratio <= 1
```

- [ ] **Step 2: Test laufen lassen – muss fehlschlagen**

Run: `pytest tests/recorder/test_cleanup.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'recorder.cleanup'`

- [ ] **Step 3: Implementierung**

`receiver/recorder/src/recorder/cleanup.py`:

```python
"""Löschen quittierter Rohdateien nach Ablauf der Vorhaltezeit."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from recorder.files import COMPLETE_SUFFIX

ACK_SUFFIX = ".ack"


def cleanup(
    complete_dir: Path, acked_dir: Path, retention_days: float, now: datetime
) -> list[Path]:
    """Löscht quittierte Dateien älter als die Vorhaltezeit. Ohne Quittung wird nie gelöscht."""
    cutoff = now.timestamp() - retention_days * 86400
    deleted = []
    for gz in sorted(complete_dir.rglob(f"*{COMPLETE_SUFFIX}")):
        rel = gz.relative_to(complete_dir)
        ack = acked_dir / rel.parent / (rel.name + ACK_SUFFIX)
        if not ack.exists() or gz.stat().st_mtime > cutoff:
            continue
        gz.unlink()
        gz.with_name(gz.name + ".sha256").unlink(missing_ok=True)
        ack.unlink()
        deleted.append(rel)

    # Verwaiste Quittungen (Datei schon gelöscht oder nie vorhanden) nach derselben Frist entfernen.
    for ack in acked_dir.rglob(f"*{ACK_SUFFIX}"):
        rel = ack.relative_to(acked_dir)
        data = complete_dir / rel.parent / rel.name.removesuffix(ACK_SUFFIX)
        if not data.exists() and ack.stat().st_mtime <= cutoff:
            ack.unlink()
    return deleted


def free_space(path: Path) -> tuple[int, float]:
    usage = shutil.disk_usage(path)
    return usage.free, usage.free / usage.total
```

- [ ] **Step 4: Test laufen lassen – muss bestehen**

Run: `pytest tests/recorder/test_cleanup.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add receiver/recorder/src/recorder/cleanup.py tests/recorder/test_cleanup.py
git commit -m "recorder: Aufräumen quittierter Dateien und Speicherstatus"
```

---

### Task 5: recorder – Datenquelle, Uhr, Hauptschleife, Container

**Files:**
- Create: `receiver/recorder/src/recorder/config.py`, `source.py`, `clock.py`, `logjson.py`, `main.py`, `health.py`, `__main__.py`
- Create: `receiver/recorder/Dockerfile`
- Create: `tests/fixtures/synthetic/__init__.py`, `tests/fixtures/synthetic/generator.py`
- Test: `tests/recorder/test_source.py`, `tests/recorder/test_clock.py`, `tests/recorder/test_main.py`, `tests/recorder/test_config.py`

**Interfaces:**
- Consumes: Tasks 2–4
- Produces:
  - `recorder.config.Config` (frozen dataclass): `receiver_id: str`, `readsb_url: str`, `data_dir: Path`, `rotate_seconds: int = 3600`, `max_data_age_s: float = 5.0`, `retention_days: float = 7`, `min_free_ratio: float = 0.10`, `ntp_server: str = "pool.ntp.org"`, `synthetic: bool = False`; `Config.from_env(env: Mapping[str, str]) -> Config`
  - Umgebungsvariablen: `RECEIVER_ID` (Pflicht), `READSB_URL` (Pflicht), `RECORDER_DATA_DIR` (Standard `/data`), `RECORDER_ROTATE_SECONDS`, `RECORDER_MAX_DATA_AGE_S`, `RECEIVER_RETENTION_DAYS`, `RECORDER_MIN_FREE_RATIO`, `RECORDER_NTP_SERVER`, `RECORDER_SYNTHETIC` (`1`/`0`)
  - `recorder.source.fetch_aircraft(url: str, timeout: float = 2.0) -> dict | None`
  - `recorder.clock.sntp_offset(server: str, port: int = 123, timeout: float = 2.0) -> float | None`
  - `recorder.main.Recorder(cfg, fetch=None, now_fn=utcnow, clock_fn=None)` mit `start()`, `tick()`, `stop()`; Attribute `current_dir`, `complete_dir`, `acked_dir`, `heartbeat`; `recorder.main.run(cfg, stop: threading.Event) -> None`
  - `recorder.health.main(path: Path | None = None, max_age_s: float = 10.0) -> int`
  - `synthetic.generator.aircraft(hex="ff0001", lat=50.0, lon=10.0, seen_pos=0.5, alt_baro=3000, **extra) -> dict`, `synthetic.generator.snapshot(now: float, planes: list[dict]) -> dict`

- [ ] **Step 1: Synthetischen Generator anlegen**

`tests/fixtures/synthetic/__init__.py`:

```python
"""Synthetische Testdaten – keine echten Flugbewegungen."""
```

`tests/fixtures/synthetic/generator.py`:

```python
"""Erzeugt aircraft.json-Daten im readsb-Format.

Alle ICAO24-Kennungen beginnen mit ``ff``, Koordinaten sind frei gewählt,
jede Momentaufnahme trägt ``"synthetic": true``.
"""

from __future__ import annotations


def aircraft(
    hex: str = "ff0001",
    lat: float = 50.0,
    lon: float = 10.0,
    seen_pos: float | None = 0.5,
    alt_baro: int | str = 3000,
    **extra,
) -> dict:
    ac = {
        "hex": hex,
        "type": "adsb_icao",
        "flight": "TEST01  ",
        "r": "TEST-REG",
        "t": "TST1",
        "alt_baro": alt_baro,
        "alt_geom": alt_baro + 100 if isinstance(alt_baro, int) else None,
        "gs": 180.0,
        "track": 90.0,
        "baro_rate": 0,
        "squawk": "7000",
        "lat": lat,
        "lon": lon,
        "nic": 8,
        "nac_p": 9,
        "sil": 3,
        "seen_pos": seen_pos,
        "seen": 0.1,
        "rssi": -20.5,
    }
    ac.update(extra)
    return {k: v for k, v in ac.items() if v is not None}


def snapshot(now: float, planes: list[dict]) -> dict:
    return {"now": now, "messages": 1000, "synthetic": True, "aircraft": planes}
```

- [ ] **Step 2: Failing Tests schreiben**

`tests/recorder/test_config.py`:

```python
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
```

`tests/recorder/test_source.py`:

```python
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from recorder.source import fetch_aircraft


@pytest.fixture
def server():
    responses = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = responses.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", responses
    httpd.shutdown()


def test_valid_json(server):
    base, responses = server
    responses["/ok"] = json.dumps({"now": 1.0, "aircraft": []}).encode()
    assert fetch_aircraft(base + "/ok") == {"now": 1.0, "aircraft": []}


def test_invalid_inputs_return_none(server):
    base, responses = server
    responses["/bad"] = b"{not json"
    responses["/nonow"] = b'{"aircraft": []}'
    assert fetch_aircraft(base + "/bad") is None
    assert fetch_aircraft(base + "/nonow") is None
    assert fetch_aircraft(base + "/missing") is None
    assert fetch_aircraft("http://127.0.0.1:1/unreachable", timeout=0.5) is None
```

`tests/recorder/test_clock.py`:

```python
import socket
import struct
import threading
import time

from recorder.clock import NTP_DELTA, sntp_offset


def fake_ntp_server(skew_s):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))

    def serve():
        _, addr = sock.recvfrom(48)
        t = time.time() + skew_s + NTP_DELTA
        sec, frac = int(t), int((t % 1) * 2**32)
        reply = bytearray(48)
        reply[0] = 0x1C
        reply[32:40] = struct.pack("!II", sec, frac)
        reply[40:48] = struct.pack("!II", sec, frac)
        sock.sendto(bytes(reply), addr)
        sock.close()

    threading.Thread(target=serve, daemon=True).start()
    return sock.getsockname()[1]


def test_measures_offset():
    port = fake_ntp_server(10.0)
    offset = sntp_offset("127.0.0.1", port=port)
    assert offset is not None
    assert abs(offset - 10.0) < 0.5


def test_unreachable_returns_none():
    assert sntp_offset("127.0.0.1", port=9, timeout=0.3) is None
```

`tests/recorder/test_main.py`:

```python
import gzip
import json
import os
from datetime import UTC, datetime, timedelta

from synthetic.generator import aircraft, snapshot

from recorder.config import Config
from recorder.main import Recorder

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


def make_cfg(tmp_path):
    return Config(
        receiver_id="TEST", readsb_url="http://unused", data_dir=tmp_path, synthetic=True
    )


def read_all(complete_dir):
    lines = []
    for gz in sorted(complete_dir.rglob("*.ndjson.gz")):
        lines += [json.loads(line) for line in gzip.open(gz, "rt").read().splitlines()]
    return lines


def test_snapshots_gap_and_housekeeping(tmp_path):
    clock = FakeClock(T0)
    available = iter([True, True, False, False, True])

    def fetch():
        if next(available):
            return snapshot(clock().timestamp(), [aircraft()])
        return None

    rec = Recorder(make_cfg(tmp_path), fetch=fetch, now_fn=clock, clock_fn=lambda: 0.02)
    rec.start()
    for _ in range(5):
        rec.tick()
        clock.advance(1)
    rec.stop()

    lines = read_all(rec.complete_dir)
    assert [line["type"] for line in lines] == [
        "snapshot",
        "clock",
        "status",
        "snapshot",
        "gap",
        "snapshot",
    ]
    gap = lines[4]
    assert (gap["from"], gap["to"], gap["reason"]) == (
        "2026-11-09T14:00:01.000Z",
        "2026-11-09T14:00:04.000Z",
        "no_data",
    )
    assert all(line["synthetic"] is True and line["receiver_id"] == "TEST" for line in lines)
    assert lines[1]["offset_s"] == 0.02
    assert list(rec.complete_dir.rglob("*.partial.ndjson.gz"))


def test_unchanged_readsb_timestamp_is_not_written_twice(tmp_path):
    clock = FakeClock(T0)
    frozen = snapshot(T0.timestamp(), [aircraft()])
    rec = Recorder(make_cfg(tmp_path), fetch=lambda: frozen, now_fn=clock, clock_fn=lambda: 0)
    rec.start()
    rec.tick()
    clock.advance(1)
    rec.tick()
    rec.stop()
    types = [line["type"] for line in read_all(rec.complete_dir)]
    assert types.count("snapshot") == 1


def test_restart_recovers_file_and_logs_gap(tmp_path):
    stale = tmp_path / "current/TEST/2026/11/09/20261109T130000Z.ndjson"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b'{"type":"snapshot"}\n{"type":')
    last = (T0 - timedelta(minutes=10)).timestamp()
    os.utime(stale, (last, last))

    clock = FakeClock(T0)
    rec = Recorder(make_cfg(tmp_path), fetch=lambda: None, now_fn=clock, clock_fn=lambda: None)
    rec.start()
    rec.stop()

    recovered = rec.complete_dir / "TEST/2026/11/09/20261109T130000Z.partial.ndjson.gz"
    assert gzip.decompress(recovered.read_bytes()) == b'{"type":"snapshot"}\n'
    gaps = [line for line in read_all(rec.complete_dir) if line["type"] == "gap"]
    assert gaps[0]["reason"] == "recorder_restart"
    assert gaps[0]["from"] == "2026-11-09T13:50:00.000Z"


def test_heartbeat_only_with_fresh_data(tmp_path):
    clock = FakeClock(T0)
    rec = Recorder(make_cfg(tmp_path), fetch=lambda: None, now_fn=clock, clock_fn=lambda: 0)
    rec.start()
    rec.tick()
    assert not rec.heartbeat.exists()
    rec._fetch = lambda: snapshot(clock().timestamp(), [])
    clock.advance(1)
    rec.tick()
    assert rec.heartbeat.exists()
    rec.stop()
```

- [ ] **Step 3: Tests laufen lassen – müssen fehlschlagen**

Run: `pytest tests/recorder -v`
Expected: FAIL mit `ModuleNotFoundError` für `recorder.config`, `recorder.source`, `recorder.clock`, `recorder.main`

- [ ] **Step 4: Implementierung**

`receiver/recorder/src/recorder/config.py`:

```python
"""Konfiguration aus Umgebungsvariablen."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    receiver_id: str
    readsb_url: str
    data_dir: Path = Path("/data")
    rotate_seconds: int = 3600
    max_data_age_s: float = 5.0
    retention_days: float = 7
    min_free_ratio: float = 0.10
    ntp_server: str = "pool.ntp.org"
    synthetic: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        return cls(
            receiver_id=env["RECEIVER_ID"],
            readsb_url=env["READSB_URL"],
            data_dir=Path(env.get("RECORDER_DATA_DIR", "/data")),
            rotate_seconds=int(env.get("RECORDER_ROTATE_SECONDS", "3600")),
            max_data_age_s=float(env.get("RECORDER_MAX_DATA_AGE_S", "5")),
            retention_days=float(env.get("RECEIVER_RETENTION_DAYS", "7")),
            min_free_ratio=float(env.get("RECORDER_MIN_FREE_RATIO", "0.10")),
            ntp_server=env.get("RECORDER_NTP_SERVER", "pool.ntp.org"),
            synthetic=env.get("RECORDER_SYNTHETIC", "0") == "1",
        )
```

`receiver/recorder/src/recorder/source.py`:

```python
"""Abruf der aktuellen Flugzeugliste von readsb."""

from __future__ import annotations

import http.client
import json
import urllib.request


def fetch_aircraft(url: str, timeout: float = 2.0) -> dict | None:
    """Liest ``aircraft.json``. Gibt ``None`` zurück, wenn nichts Verwertbares kommt."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("now"), int | float):
        return None
    return data
```

`receiver/recorder/src/recorder/clock.py`:

```python
"""Messung der Uhrabweichung per SNTP (RFC 4330)."""

from __future__ import annotations

import socket
import struct
import time

NTP_DELTA = 2208988800  # Sekunden zwischen 1900-01-01 und 1970-01-01


def _ntp_time(raw: bytes) -> float:
    sec, frac = struct.unpack("!II", raw)
    return sec - NTP_DELTA + frac / 2**32


def sntp_offset(server: str, port: int = 123, timeout: float = 2.0) -> float | None:
    """Abweichung der Systemuhr zum Server in Sekunden (positiv: Systemuhr geht nach)."""
    request = b"\x1b" + 47 * b"\0"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            t1 = time.time()
            s.sendto(request, (server, port))
            data, _ = s.recvfrom(48)
            t4 = time.time()
    except OSError:
        return None
    if len(data) < 48:
        return None
    t2, t3 = _ntp_time(data[32:40]), _ntp_time(data[40:48])
    return ((t2 - t1) + (t3 - t4)) / 2
```

`receiver/recorder/src/recorder/logjson.py`:

```python
"""Strukturierte JSON-Logs nach stdout."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        out.update({k: v for k, v in vars(record).items() if k not in _STANDARD})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
```

`receiver/recorder/src/recorder/main.py`:

```python
"""Hauptschleife des recorders."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from recorder import __version__
from recorder.cleanup import cleanup, free_space
from recorder.clock import sntp_offset
from recorder.config import Config
from recorder.files import last_activity, recover
from recorder.gaps import GapDetector
from recorder.source import fetch_aircraft
from recorder.timeutil import iso, utcnow
from recorder.writer import RotatingWriter

log = logging.getLogger("recorder")

HOUSEKEEPING_INTERVAL = timedelta(hours=1)
MAX_CLOCK_OFFSET_S = 1.0


class Recorder:
    def __init__(
        self,
        cfg: Config,
        fetch: Callable[[], dict | None] | None = None,
        now_fn: Callable[[], datetime] = utcnow,
        clock_fn: Callable[[], float | None] | None = None,
    ) -> None:
        self.cfg = cfg
        self._fetch = fetch or (lambda: fetch_aircraft(cfg.readsb_url))
        self._now = now_fn
        self._clock = clock_fn or (lambda: sntp_offset(cfg.ntp_server))
        self.current_dir = cfg.data_dir / "current"
        self.complete_dir = cfg.data_dir / "complete"
        self.acked_dir = cfg.data_dir / "acked"
        self.heartbeat = cfg.data_dir / "heartbeat"
        self._writer = RotatingWriter(
            cfg.receiver_id, self.current_dir, self.complete_dir, cfg.rotate_seconds
        )
        self._gaps = GapDetector(cfg.max_data_age_s)
        self._last_data_now: float | None = None
        self._next_housekeeping: datetime | None = None

    def _record(self, kind: str, now: datetime, **fields) -> None:
        rec = {
            "type": kind,
            "recorder_ts": iso(now),
            "receiver_id": self.cfg.receiver_id,
            "recorder_version": __version__,
        }
        if self.cfg.synthetic:
            rec["synthetic"] = True
        rec.update(fields)
        finished = self._writer.write(rec, now)
        if finished is not None:
            log.info("Datei abgeschlossen", extra={"file": str(finished)})

    def start(self) -> None:
        for d in (self.current_dir, self.complete_dir, self.acked_dir):
            d.mkdir(parents=True, exist_ok=True)
        previous = last_activity(self.current_dir, self.complete_dir)
        for path in recover(self.current_dir, self.complete_dir):
            log.warning("Unvollständige Datei abgeschlossen", extra={"file": str(path)})
        if previous is not None:
            now = self._now()
            self._record("gap", now, **{"from": iso(previous), "to": iso(now)}, reason="recorder_restart")

    def tick(self) -> None:
        now = self._now()
        data = self._fetch()
        data_ts = datetime.fromtimestamp(data["now"], tz=UTC) if data is not None else None
        gap = self._gaps.observe(now, data_ts)
        if gap is not None:
            self._record("gap", now, **gap)
        if data is not None and data["now"] != self._last_data_now:
            self._record("snapshot", now, data=data)
            self._last_data_now = data["now"]
            if not self._gaps.in_gap:
                self.heartbeat.touch()
        if self._next_housekeeping is None or now >= self._next_housekeeping:
            self._housekeeping(now)
            self._next_housekeeping = now + HOUSEKEEPING_INTERVAL
        finished = self._writer.rotate_if_due(now)
        if finished is not None:
            log.info("Datei abgeschlossen", extra={"file": str(finished)})

    def _housekeeping(self, now: datetime) -> None:
        offset = self._clock()
        self._record("clock", now, offset_s=offset)
        if offset is None:
            log.warning("Uhrabweichung nicht messbar")
        elif abs(offset) > MAX_CLOCK_OFFSET_S:
            log.warning("Uhrabweichung zu groß", extra={"offset_s": offset})

        free_bytes, free_ratio = free_space(self.cfg.data_dir)
        self._record("status", now, free_bytes=free_bytes, free_ratio=round(free_ratio, 4))
        if free_ratio < self.cfg.min_free_ratio:
            log.warning("Pufferspeicher knapp", extra={"free_ratio": free_ratio})

        deleted = cleanup(self.complete_dir, self.acked_dir, self.cfg.retention_days, now)
        if deleted:
            log.info("Quittierte Dateien gelöscht", extra={"count": len(deleted)})

    def stop(self) -> None:
        now = self._now()
        gap = self._gaps.flush(now)
        if gap is not None:
            self._record("gap", now, **gap)
        finished = self._writer.close(partial=True)
        if finished is not None:
            log.info("Datei bei Beenden abgeschlossen", extra={"file": str(finished)})


def run(cfg: Config, stop: threading.Event) -> None:
    rec = Recorder(cfg)
    rec.start()
    log.info("recorder gestartet", extra={"receiver_id": cfg.receiver_id, "version": __version__})
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            rec.tick()
        except Exception:
            log.exception("Fehler in der Hauptschleife")
        stop.wait(max(0.0, 1.0 - (time.monotonic() - t0)))
    rec.stop()
    log.info("recorder beendet")
```

`receiver/recorder/src/recorder/health.py`:

```python
"""Healthcheck: gesund, wenn der Heartbeat jünger als ``max_age_s`` ist."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main(path: Path | None = None, max_age_s: float = 10.0) -> int:
    path = path or Path(os.environ.get("RECORDER_DATA_DIR", "/data")) / "heartbeat"
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return 1
    return 0 if age <= max_age_s else 1


if __name__ == "__main__":
    sys.exit(main())
```

`receiver/recorder/src/recorder/__main__.py`:

```python
"""Einstiegspunkt: ``python -m recorder``."""

import os
import signal
import threading

from recorder.config import Config
from recorder.logjson import setup_logging
from recorder.main import run


def main() -> None:
    setup_logging()
    os.umask(0o002)  # Gruppe flightdb muss lesen (Abholung) und Verzeichnisse schreiben dürfen
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run(Config.from_env(), stop)


if __name__ == "__main__":
    main()
```

`receiver/recorder/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY src/ /app/
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-m", "recorder.health"]

CMD ["python", "-m", "recorder"]
```

Hinweis: Der Benutzer (`user:`) wird in der Compose-Datei gesetzt (Task 11), damit UID/GID zur Gruppe `flightdb` auf dem Pi passen.

- [ ] **Step 5: Tests laufen lassen – müssen bestehen**

Run: `pytest tests/recorder -v && ruff check . && ruff format --check .`
Expected: alle recorder-Tests PASS. Falls ruff die lange `_record("gap", …)`-Zeile in `start()` umbricht: `ruff format .` und erneut prüfen.

- [ ] **Step 6: Image bauen (Smoke-Test)**

Run: `docker build -t flightdb-recorder:dev receiver/recorder && docker run --rm flightdb-recorder:dev python -c "import recorder; print(recorder.__version__)"`
Expected: `0.1.0`

- [ ] **Step 7: Commit**

```bash
git add receiver/recorder tests/recorder tests/fixtures/synthetic
git commit -m "recorder: Hauptschleife, SNTP-Uhrabgleich, Healthcheck und Container"
```

---

### Task 6: Datenbank – Schema, Rollen, Migrationen

**Files:**
- Create: `database/migrations/001_erfassung.sql`, `database/init/10-roles.sh`
- Create: `ingest/src/ingest/__init__.py`, `ingest/src/ingest/db.py` (zunächst nur `migrate`)
- Create: `tests/conftest.py`, `tests/compose.test.yml`
- Test: `tests/db/test_schema.py`

**Interfaces:**
- Produces:
  - `ingest.__version__: str`
  - `ingest.db.migrate(conn: psycopg.Connection, migrations_dir: Path) -> list[str]` (Namen neu eingespielter Dateien; Verbindung mit `autocommit=True`)
  - Fixture `db_dsns` → `{"admin": str, "ingest": str, "reader": str}` (eigene Wegwerf-Datenbank je Test, Schema migriert)
  - Konstante `tests.conftest.MIGRATIONS: Path`
  - Rollen `flightdb_ingest`, `flightdb_reader`; Tabellen gemäß Spezifikation 5.1; View `ingest_status`

- [ ] **Step 1: Lokale Test-Datenbank**

`tests/compose.test.yml`:

```yaml
# Lokale PostGIS-Instanz für Integrationstests:
#   docker compose -f tests/compose.test.yml up -d
#   export TEST_ADMIN_DSN=postgresql://postgres:test@localhost:55432/postgres
services:
  postgis:
    image: postgis/postgis:16-3.4
    platform: linux/amd64
    environment:
      POSTGRES_PASSWORD: test
    ports:
      - "55432:5432"
```

Run: `docker compose -f tests/compose.test.yml up -d && export TEST_ADMIN_DSN=postgresql://postgres:test@localhost:55432/postgres`

- [ ] **Step 2: Fixture und Failing Tests schreiben**

`tests/conftest.py`:

```python
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import conninfo

MIGRATIONS = Path(__file__).resolve().parents[1] / "database" / "migrations"


@pytest.fixture
def db_dsns():
    """Eigene, migrierte Wegwerf-Datenbank je Test; benötigt TEST_ADMIN_DSN."""
    admin = os.environ.get("TEST_ADMIN_DSN")
    if not admin:
        pytest.skip("TEST_ADMIN_DSN nicht gesetzt")
    from ingest.db import migrate

    name = f"flightdb_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    params = conninfo.conninfo_to_dict(admin) | {"dbname": name}
    admin_dsn = conninfo.make_conninfo(**params)
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        migrate(c, MIGRATIONS)
        c.execute("ALTER ROLE flightdb_ingest LOGIN PASSWORD 'test'")
        c.execute("ALTER ROLE flightdb_reader LOGIN PASSWORD 'test'")

    def as_role(role):
        return conninfo.make_conninfo(**(params | {"user": role, "password": "test"}))

    yield {
        "admin": admin_dsn,
        "ingest": as_role("flightdb_ingest"),
        "reader": as_role("flightdb_reader"),
    }
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
```

`tests/db/test_schema.py`:

```python
import psycopg
import pytest

from conftest import MIGRATIONS
from ingest.db import migrate

pytestmark = pytest.mark.db


def test_migrate_is_idempotent(db_dsns):
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        assert migrate(c, MIGRATIONS) == []
        versions = [r[0] for r in c.execute("SELECT version FROM schema_migrations")]
        assert versions == ["001_erfassung.sql"]


def test_positions_is_partitioned(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c:
        kind = c.execute("SELECT relkind FROM pg_class WHERE relname = 'positions'").fetchone()
        assert kind == ("p",)


def test_reader_cannot_write(db_dsns):
    with psycopg.connect(db_dsns["reader"]) as c:
        assert c.execute("SELECT count(*) FROM ingest_status").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO receivers (id, label) VALUES ('X', 'x')")


def test_ingest_can_write_receivers(db_dsns):
    with psycopg.connect(db_dsns["ingest"]) as c:
        c.execute("INSERT INTO receivers (id, label) VALUES ('TEST', 'Test')")
        c.commit()
```

`tests/conftest.py` liegt in `tests/`, daher funktioniert `from conftest import MIGRATIONS` (pytest fügt das Verzeichnis per rootdir-conftest ein). Falls nicht: `tests` zu `pythonpath` in `pyproject.toml` hinzufügen.

- [ ] **Step 3: Tests laufen lassen – müssen fehlschlagen**

Run: `pytest tests/db -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ingest'`

- [ ] **Step 4: Migration, Init-Skript und Runner**

`database/migrations/001_erfassung.sql`:

```sql
-- Meilenstein 2: Tabellen für Erfassung und Herkunft der Daten.
-- Einheiten wie readsb: Fuß (ft), Knoten (kt), ft/min. Zeiten in UTC.

CREATE EXTENSION IF NOT EXISTS postgis;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'flightdb_ingest') THEN
    CREATE ROLE flightdb_ingest NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'flightdb_reader') THEN
    CREATE ROLE flightdb_reader NOLOGIN;
  END IF;
END
$$;

CREATE TABLE receivers (
  id          text PRIMARY KEY,
  label       text NOT NULL,
  location    geometry(Point, 4326),
  altitude_m  real,
  antenna     text,
  sdr         text,
  valid_from  timestamptz NOT NULL DEFAULT now(),
  valid_to    timestamptz
);

CREATE TABLE raw_files (
  id                   bigserial PRIMARY KEY,
  receiver_id          text NOT NULL REFERENCES receivers (id),
  path                 text NOT NULL UNIQUE,
  sha256               char(64) NOT NULL UNIQUE,
  size_bytes           bigint NOT NULL,
  period_start         timestamptz,
  period_end           timestamptz,
  partial              boolean NOT NULL DEFAULT false,
  clock_offset_max_s   real,
  receiver_free_bytes  bigint,
  fetched_at           timestamptz NOT NULL DEFAULT now(),
  status               text NOT NULL CHECK (status IN ('registered', 'ingested', 'failed')),
  ingest_version       text NOT NULL,
  error                text
);

CREATE TABLE reception_gaps (
  id           bigserial PRIMARY KEY,
  receiver_id  text NOT NULL REFERENCES receivers (id),
  gap_start    timestamptz NOT NULL,
  gap_end      timestamptz NOT NULL,
  reason       text NOT NULL,
  raw_file_id  bigint NOT NULL REFERENCES raw_files (id) ON DELETE CASCADE,
  UNIQUE (receiver_id, gap_start, gap_end, reason)
);

CREATE TABLE aircraft (
  icao24        text PRIMARY KEY,
  registration  text,
  type_code     text,
  first_seen    timestamptz NOT NULL,
  last_seen     timestamptz NOT NULL
);

-- raw_file_id ohne Fremdschlüssel: kein Zusatzindex auf der größten Tabelle.
CREATE TABLE positions (
  ts             timestamptz NOT NULL,
  receiver_id    text NOT NULL,
  icao24         text NOT NULL,
  callsign       text,
  geom           geometry(Point, 4326) NOT NULL,
  on_ground      boolean NOT NULL DEFAULT false,
  alt_baro_ft    integer,
  alt_geom_ft    integer,
  gs_kt          real,
  track_deg      real,
  baro_rate_fpm  integer,
  squawk         text,
  source_type    text,
  nic            smallint,
  nac_p          smallint,
  sil            smallint,
  rssi_dbfs      real,
  raw_file_id    bigint NOT NULL,
  PRIMARY KEY (receiver_id, icao24, ts)
) PARTITION BY RANGE (ts);

CREATE INDEX positions_ts_brin ON positions USING brin (ts);
CREATE INDEX positions_geom_gist ON positions USING gist (geom);

CREATE VIEW ingest_status AS
SELECT
  r.id AS receiver_id,
  (SELECT max(f.period_end) FROM raw_files f
    WHERE f.receiver_id = r.id AND f.status = 'ingested') AS last_ingested_period_end,
  (SELECT max(f.fetched_at) FROM raw_files f WHERE f.receiver_id = r.id) AS last_fetched_at,
  (SELECT count(*) FROM raw_files f
    WHERE f.receiver_id = r.id AND f.status <> 'ingested') AS files_not_ingested,
  (SELECT count(*) FROM reception_gaps g
    WHERE g.receiver_id = r.id AND g.gap_end > now() - interval '24 hours') AS gaps_24h,
  (SELECT coalesce(sum(extract(epoch FROM
      least(g.gap_end, now()) - greatest(g.gap_start, now() - interval '24 hours'))), 0)
    FROM reception_gaps g
    WHERE g.receiver_id = r.id AND g.gap_end > now() - interval '24 hours') AS gap_seconds_24h,
  (SELECT f.receiver_free_bytes FROM raw_files f
    WHERE f.receiver_id = r.id AND f.receiver_free_bytes IS NOT NULL
    ORDER BY f.period_end DESC NULLS LAST LIMIT 1) AS receiver_free_bytes
FROM receivers r;

GRANT USAGE ON SCHEMA public TO flightdb_ingest, flightdb_reader;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON receivers, raw_files, reception_gaps, aircraft, positions TO flightdb_ingest;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO flightdb_ingest;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO flightdb_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO flightdb_reader;
```

`database/init/10-roles.sh`:

```bash
#!/bin/bash
# Läuft einmalig beim ersten Start des PostGIS-Containers (leeres Datenverzeichnis).
# Legt die Anwendungsrollen mit Passwörtern aus der .env an; Rechte vergibt die Migration.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v ingest_pw="$DB_INGEST_PASSWORD" -v reader_pw="$DB_READONLY_PASSWORD" <<'SQL'
CREATE ROLE flightdb_ingest LOGIN PASSWORD :'ingest_pw';
CREATE ROLE flightdb_reader LOGIN PASSWORD :'reader_pw';
SQL
```

`ingest/src/ingest/__init__.py`:

```python
"""Abholung, Archivierung und Laden der Rohdaten auf dem NAS."""

__version__ = "0.1.0"
```

`ingest/src/ingest/db.py`:

```python
"""Datenbankzugriffe von ingest."""

from __future__ import annotations

from pathlib import Path

import psycopg


def migrate(conn: psycopg.Connection, migrations_dir: Path) -> list[str]:
    """Spielt noch nicht angewendete SQL-Dateien in Namensreihenfolge ein."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied
```

Run: `chmod +x database/init/10-roles.sh`

- [ ] **Step 5: Tests laufen lassen – müssen bestehen**

Run: `pytest tests/db -v`
Expected: 4 passed (ohne `TEST_ADMIN_DSN`: 4 skipped)

- [ ] **Step 6: Init-Skript im echten Container prüfen**

```bash
docker run -d --name pg-init-test --platform linux/amd64 \
  -e POSTGRES_DB=flightdb -e POSTGRES_USER=flightdb_admin -e POSTGRES_PASSWORD=a \
  -e DB_INGEST_PASSWORD=i -e DB_READONLY_PASSWORD=r \
  -v "$PWD/database/init:/docker-entrypoint-initdb.d:ro" postgis/postgis:16-3.4
sleep 15
docker exec pg-init-test psql -U flightdb_admin -d flightdb -tAc \
  "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname LIKE 'flightdb_%' ORDER BY 1"
docker rm -f pg-init-test
```

Expected: `flightdb_admin|t`, `flightdb_ingest|t`, `flightdb_reader|t`

- [ ] **Step 7: Commit**

```bash
git add database ingest/src/ingest/__init__.py ingest/src/ingest/db.py tests/conftest.py \
  tests/compose.test.yml tests/db
git commit -m "Datenbank: Erfassungsschema, Rollen und Migrationen"
```

---

### Task 7: ingest – Prüfsummen und Normalisierung

**Files:**
- Create: `ingest/src/ingest/checksum.py`, `ingest/src/ingest/parse.py`
- Create: `tests/fixtures/synthetic/rawfiles.py`
- Test: `tests/ingest/test_checksum.py`, `tests/ingest/test_parse.py`

**Interfaces:**
- Consumes: `recorder.writer.RotatingWriter`, `recorder.timeutil.iso` (nur in Test-Hilfen)
- Produces:
  - `ingest.checksum.sha256_file(path: Path) -> str`, `read_sidecar(path: Path) -> str`, `verify(data: Path, sidecar: Path) -> bool`
  - `ingest.parse`: Dataclasses `Position` (Felder: `ts, icao24, callsign, lon, lat, on_ground, alt_baro_ft, alt_geom_ft, gs_kt, track_deg, baro_rate_fpm, squawk, source_type, nic, nac_p, sil, rssi_dbfs`), `Gap(start, end, reason)`, `AircraftSeen(icao24, registration, type_code, first_seen, last_seen)`, `ParsedFile(receiver_id, synthetic, positions, gaps, aircraft: dict[str, AircraftSeen], period_start, period_end, clock_offset_max_s, receiver_free_bytes, bad_lines)`; Konstante `POSITION_FIELDS: tuple[str, ...]`; Ausnahme `InconsistentFile(ValueError)`; `parse_file(path: Path) -> ParsedFile`
  - `synthetic.rawfiles.write_raw_file(complete_dir: Path, start: datetime, snapshots: list[dict], receiver_id: str = "TEST", extra: list[dict] = ()) -> Path`, `line(kind: str, ts: datetime, receiver_id: str = "TEST", **fields) -> dict`

- [ ] **Step 1: Test-Hilfe für Rohdateien**

`tests/fixtures/synthetic/rawfiles.py`:

```python
"""Erzeugt synthetische Rohdateien genau so, wie der recorder sie schreibt."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from recorder.timeutil import iso
from recorder.writer import RotatingWriter


def line(kind: str, ts: datetime, receiver_id: str = "TEST", **fields) -> dict:
    return {
        "type": kind,
        "recorder_ts": iso(ts),
        "receiver_id": receiver_id,
        "recorder_version": "test",
        "synthetic": True,
        **fields,
    }


def write_raw_file(
    complete_dir: Path,
    start: datetime,
    snapshots: list[dict],
    receiver_id: str = "TEST",
    extra: list[dict] = (),
) -> Path:
    """Eine Momentaufnahme je Sekunde ab ``start``, danach ``extra``-Zeilen; mit .sha256."""
    writer = RotatingWriter(receiver_id, complete_dir.parent / ".fixture-current", complete_dir, 3600)
    for i, data in enumerate(snapshots):
        ts = start + timedelta(seconds=i)
        writer.write(line("snapshot", ts, receiver_id, data=data), ts)
    for rec in extra:
        writer.write(rec, start)
    return writer.close()
```

- [ ] **Step 2: Failing Tests schreiben**

`tests/ingest/test_checksum.py`:

```python
from ingest.checksum import read_sidecar, sha256_file, verify


def test_verify(tmp_path):
    data = tmp_path / "a.ndjson.gz"
    data.write_bytes(b"abc")
    sidecar = tmp_path / "a.ndjson.gz.sha256"
    sidecar.write_text(f"{sha256_file(data)}  a.ndjson.gz\n")
    assert read_sidecar(sidecar) == sha256_file(data)
    assert verify(data, sidecar)
    data.write_bytes(b"abd")
    assert not verify(data, sidecar)


def test_verify_missing_or_garbage_sidecar(tmp_path):
    data = tmp_path / "a"
    data.write_bytes(b"x")
    assert not verify(data, tmp_path / "missing")
    bad = tmp_path / "bad"
    bad.write_text("nonsense")
    assert not verify(data, bad)
```

`tests/ingest/test_parse.py`:

```python
from datetime import UTC, datetime

import pytest
from synthetic.generator import aircraft, snapshot
from synthetic.rawfiles import line, write_raw_file

from ingest.parse import InconsistentFile, parse_file

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
NOW = T0.timestamp()


def test_position_time_from_seen_pos(tmp_path):
    path = write_raw_file(tmp_path, T0, [snapshot(NOW + 10.0, [aircraft(seen_pos=2.3)])])
    parsed = parse_file(path)
    (pos,) = parsed.positions
    assert pos.ts == datetime(2026, 11, 9, 14, 0, 7, 700000, tzinfo=UTC)
    assert (pos.icao24, pos.callsign, pos.lat, pos.lon) == ("ff0001", "TEST01", 50.0, 10.0)
    assert (pos.alt_baro_ft, pos.alt_geom_ft, pos.source_type, pos.rssi_dbfs) == (
        3000,
        3100,
        "adsb_icao",
        -20.5,
    )
    assert parsed.receiver_id == "TEST"
    assert parsed.synthetic is True


def test_ground_and_missing_position(tmp_path):
    planes = [aircraft(hex="ff0002", alt_baro="ground"), aircraft(hex="ff0003", seen_pos=None)]
    parsed = parse_file(write_raw_file(tmp_path, T0, [snapshot(NOW, planes)]))
    (pos,) = parsed.positions
    assert pos.icao24 == "ff0002"
    assert pos.on_ground is True
    assert pos.alt_baro_ft is None


def test_same_position_in_consecutive_snapshots_is_deduplicated(tmp_path):
    snaps = [
        snapshot(NOW, [aircraft(seen_pos=0.5)]),
        snapshot(NOW + 1.0, [aircraft(seen_pos=1.5)]),  # dieselbe Position, 1 s älter
        snapshot(NOW + 2.0, [aircraft(seen_pos=0.2)]),  # neue Position
    ]
    parsed = parse_file(write_raw_file(tmp_path, T0, snaps))
    assert len(parsed.positions) == 2
    seen = parsed.aircraft["ff0001"]
    assert (seen.registration, seen.type_code) == ("TEST-REG", "TST1")
    assert seen.first_seen < seen.last_seen


def test_gap_clock_status_and_period(tmp_path):
    extra = [
        line("gap", T0, **{"from": "2026-11-09T13:59:00.000Z", "to": "2026-11-09T13:59:30.000Z"},
             reason="no_data"),
        line("clock", T0, offset_s=-0.4),
        line("clock", T0, offset_s=0.1),
        line("clock", T0, offset_s=None),
        line("status", T0, free_bytes=12345, free_ratio=0.5),
    ]
    parsed = parse_file(write_raw_file(tmp_path, T0, [snapshot(NOW, [])] * 3, extra=extra))
    (gap,) = parsed.gaps
    assert (gap.start.second, gap.end.second, gap.reason) == (0, 30, "no_data")
    assert parsed.clock_offset_max_s == 0.4
    assert parsed.receiver_free_bytes == 12345
    assert parsed.period_start == T0
    assert parsed.period_end == datetime(2026, 11, 9, 14, 0, 2, tzinfo=UTC)


def test_mixed_receiver_ids_raise(tmp_path):
    extra = [line("status", T0, receiver_id="OTHER", free_bytes=1)]
    path = write_raw_file(tmp_path, T0, [snapshot(NOW, [])], extra=extra)
    with pytest.raises(InconsistentFile):
        parse_file(path)


def test_malformed_lines_are_counted(tmp_path):
    extra = [{"type": "snapshot"}, ["kein", "objekt"]]
    parsed = parse_file(write_raw_file(tmp_path, T0, [snapshot(NOW, [])], extra=extra))
    assert parsed.bad_lines == 2
```

- [ ] **Step 3: Tests laufen lassen – müssen fehlschlagen**

Run: `pytest tests/ingest -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'ingest.checksum'` bzw. `'ingest.parse'`

- [ ] **Step 4: Implementierung**

`ingest/src/ingest/checksum.py`:

```python
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
```

`ingest/src/ingest/parse.py`:

```python
"""Einlesen einer Rohdatei und Normalisierung zu Positionen, Lücken und Metadaten."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


class InconsistentFile(ValueError):
    """Datei enthält widersprüchliche Kopfdaten (z. B. mehrere receiver_id)."""


@dataclass(frozen=True)
class Position:
    ts: datetime
    icao24: str
    callsign: str | None
    lon: float
    lat: float
    on_ground: bool
    alt_baro_ft: int | None
    alt_geom_ft: int | None
    gs_kt: float | None
    track_deg: float | None
    baro_rate_fpm: int | None
    squawk: str | None
    source_type: str | None
    nic: int | None
    nac_p: int | None
    sil: int | None
    rssi_dbfs: float | None


POSITION_FIELDS = tuple(Position.__dataclass_fields__)


@dataclass(frozen=True)
class Gap:
    start: datetime
    end: datetime
    reason: str


@dataclass
class AircraftSeen:
    icao24: str
    registration: str | None
    type_code: str | None
    first_seen: datetime
    last_seen: datetime


@dataclass
class ParsedFile:
    receiver_id: str | None = None
    synthetic: bool = False
    positions: list[Position] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    aircraft: dict[str, AircraftSeen] = field(default_factory=dict)
    period_start: datetime | None = None
    period_end: datetime | None = None
    clock_offset_max_s: float | None = None
    receiver_free_bytes: int | None = None
    bad_lines: int = 0


def _num(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _int(v) -> int | None:
    return int(v) if _num(v) else None


def _float(v) -> float | None:
    return float(v) if _num(v) else None


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def _positions(data: dict) -> Iterator[tuple[Position, dict]]:
    now = data["now"]
    for ac in data.get("aircraft", []):
        hex_, lat, lon, seen_pos = ac.get("hex"), ac.get("lat"), ac.get("lon"), ac.get("seen_pos")
        if not isinstance(hex_, str) or not (_num(lat) and _num(lon) and _num(seen_pos)):
            continue
        alt_baro = ac.get("alt_baro")
        on_ground = alt_baro == "ground"
        yield (
            Position(
                ts=datetime.fromtimestamp(round(now - seen_pos, 1), tz=UTC),
                icao24=hex_.lower(),
                callsign=(ac.get("flight") or "").strip() or None,
                lon=float(lon),
                lat=float(lat),
                on_ground=on_ground,
                alt_baro_ft=None if on_ground else _int(alt_baro),
                alt_geom_ft=_int(ac.get("alt_geom")),
                gs_kt=_float(ac.get("gs")),
                track_deg=_float(ac.get("track")),
                baro_rate_fpm=_int(ac.get("baro_rate")),
                squawk=ac.get("squawk"),
                source_type=ac.get("type"),
                nic=_int(ac.get("nic")),
                nac_p=_int(ac.get("nac_p")),
                sil=_int(ac.get("sil")),
                rssi_dbfs=_float(ac.get("rssi")),
            ),
            ac,
        )


def _header(result: ParsedFile, rec: dict) -> None:
    rid = rec["receiver_id"]
    if result.receiver_id is None:
        result.receiver_id = rid
    elif rid != result.receiver_id:
        raise InconsistentFile(f"uneinheitliche receiver_id: {result.receiver_id!r} / {rid!r}")
    if rec.get("synthetic") is True:
        result.synthetic = True
    ts = _ts(rec["recorder_ts"])
    result.period_start = min(filter(None, (result.period_start, ts)))
    result.period_end = max(filter(None, (result.period_end, ts)))


def _snapshot(result: ParsedFile, data: dict, seen: set) -> None:
    for pos, ac in _positions(data):
        key = (pos.icao24, pos.ts)
        if key in seen:
            continue
        seen.add(key)
        result.positions.append(pos)
        known = result.aircraft.get(pos.icao24)
        if known is None:
            result.aircraft[pos.icao24] = AircraftSeen(
                pos.icao24, ac.get("r"), ac.get("t"), pos.ts, pos.ts
            )
        else:
            known.registration = ac.get("r") or known.registration
            known.type_code = ac.get("t") or known.type_code
            known.first_seen = min(known.first_seen, pos.ts)
            known.last_seen = max(known.last_seen, pos.ts)


def parse_file(path: Path) -> ParsedFile:
    result = ParsedFile()
    seen: set = set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for raw in f:
            try:
                rec = json.loads(raw)
                if not isinstance(rec, dict):
                    raise TypeError("Zeile ist kein Objekt")
                _header(result, rec)
                kind = rec["type"]
                if kind == "snapshot":
                    _snapshot(result, rec["data"], seen)
                elif kind == "gap":
                    result.gaps.append(Gap(_ts(rec["from"]), _ts(rec["to"]), rec["reason"]))
                elif kind == "clock" and _num(rec.get("offset_s")):
                    result.clock_offset_max_s = max(
                        result.clock_offset_max_s or 0.0, abs(rec["offset_s"])
                    )
                elif kind == "status" and _num(rec.get("free_bytes")):
                    result.receiver_free_bytes = int(rec["free_bytes"])
            except InconsistentFile:
                raise
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                result.bad_lines += 1
    return result
```

- [ ] **Step 5: Tests laufen lassen – müssen bestehen**

Run: `pytest tests/ingest -v && ruff check . && ruff format --check .`
Expected: alle Tests PASS (ggf. `ruff format .`).

- [ ] **Step 6: Commit**

```bash
git add ingest/src/ingest/checksum.py ingest/src/ingest/parse.py \
  tests/fixtures/synthetic/rawfiles.py tests/ingest
git commit -m "ingest: Prüfsummen und Normalisierung der Rohdaten"
```

---

### Task 8: ingest – Laden in die Datenbank

**Files:**
- Modify: `ingest/src/ingest/db.py` (Funktionen ergänzen)
- Test: `tests/db/test_load.py`

**Interfaces:**
- Consumes: `ingest.parse.ParsedFile`, `POSITION_FIELDS`; Fixture `db_dsns`
- Produces (alle mit `conn` im `autocommit`-Modus):
  - `ensure_partitions(conn, start: datetime, end: datetime) -> list[str]` (Admin-Verbindung; Namen `positions_yJJJJmMM`)
  - `ensure_receiver(conn, receiver_id: str) -> None`
  - `register_raw_file(conn, *, receiver_id: str, path: str, sha256: str, size_bytes: int, partial: bool, version: str) -> tuple[int, str]` (id, status)
  - `find_raw_file(conn, sha256: str) -> int | None`
  - `load_parsed(conn, raw_file_id: int, parsed: ParsedFile) -> int` (neu eingefügte Positionen)
  - `mark_failed(conn, raw_file_id: int, error: str) -> None`
  - `pending_files(conn) -> list[tuple[int, str, str]]` (id, path, sha256 mit Status `registered`/`failed`)
  - `delete_file_data(conn, raw_file_id: int) -> None` (Positionen und Lücken der Datei löschen, Status `registered`)

- [ ] **Step 1: Failing Tests schreiben**

`tests/db/test_load.py`:

```python
from datetime import UTC, datetime

import psycopg
import pytest
from synthetic.generator import aircraft, snapshot
from synthetic.rawfiles import line, write_raw_file

from ingest import db
from ingest.parse import parse_file

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
NOW = T0.timestamp()


@pytest.fixture
def conns(db_dsns):
    with (
        psycopg.connect(db_dsns["admin"], autocommit=True) as admin,
        psycopg.connect(db_dsns["ingest"], autocommit=True) as conn,
    ):
        yield admin, conn


def parsed_sample(tmp_path):
    snaps = [snapshot(NOW + i, [aircraft(lat=50.0 + i / 100)]) for i in range(5)]
    extra = [
        line("gap", T0, **{"from": "2026-11-09T13:59:00.000Z", "to": "2026-11-09T13:59:30.000Z"},
             reason="no_data"),
        line("status", T0, free_bytes=999),
    ]
    return parse_file(write_raw_file(tmp_path, T0, snaps, extra=extra))


def register(conn, sha="a" * 64, path="TEST/2026/11/09/20261109T140000Z.ndjson.gz"):
    db.ensure_receiver(conn, "TEST")
    return db.register_raw_file(
        conn, receiver_id="TEST", path=path, sha256=sha, size_bytes=1, partial=False,
        version="test",
    )


def test_ensure_partitions_creates_months_once(conns):
    admin, _ = conns
    start, end = datetime(2026, 12, 30, tzinfo=UTC), datetime(2027, 1, 2, tzinfo=UTC)
    assert db.ensure_partitions(admin, start, end) == ["positions_y2026m12", "positions_y2027m01"]
    assert db.ensure_partitions(admin, start, end) == []


def test_load_is_idempotent_and_complete(conns, tmp_path):
    admin, conn = conns
    parsed = parsed_sample(tmp_path)
    db.ensure_partitions(admin, T0, T0)
    raw_id, status = register(conn)
    assert status == "registered"

    assert db.load_parsed(conn, raw_id, parsed) == 5
    assert db.load_parsed(conn, raw_id, parsed) == 0

    row = conn.execute(
        "SELECT status, receiver_free_bytes, period_start FROM raw_files WHERE id = %s", (raw_id,)
    ).fetchone()
    assert row == ("ingested", 999, T0)
    assert conn.execute("SELECT count(*) FROM reception_gaps").fetchone() == (1,)
    lat = conn.execute("SELECT ST_Y(geom) FROM positions ORDER BY ts LIMIT 1").fetchone()[0]
    assert lat == pytest.approx(50.0)
    assert db.find_raw_file(conn, "a" * 64) == raw_id
    assert db.pending_files(conn) == []


def test_register_returns_existing(conns):
    _, conn = conns
    first = register(conn)
    assert register(conn) == first


def test_same_path_different_checksum_is_rejected(conns):
    _, conn = conns
    register(conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        register(conn, sha="b" * 64)


def test_aircraft_upsert_extends_range(conns, tmp_path):
    admin, conn = conns
    db.ensure_partitions(admin, T0, T0)
    a = parse_file(write_raw_file(tmp_path / "a", T0, [snapshot(NOW, [aircraft()])]))
    later = datetime(2026, 11, 9, 15, 0, 0, tzinfo=UTC)
    b = parse_file(write_raw_file(tmp_path / "b", later, [snapshot(later.timestamp(), [aircraft()])]))
    db.load_parsed(conn, register(conn)[0], a)
    db.load_parsed(conn, register(conn, "c" * 64, "TEST/x2.ndjson.gz")[0], b)
    first, last = conn.execute(
        "SELECT first_seen, last_seen FROM aircraft WHERE icao24 = 'ff0001'"
    ).fetchone()
    assert last - first > (later - T0) * 0.9


def test_failed_and_delete(conns, tmp_path):
    admin, conn = conns
    parsed = parsed_sample(tmp_path)
    db.ensure_partitions(admin, T0, T0)
    raw_id, _ = register(conn)
    db.load_parsed(conn, raw_id, parsed)

    db.delete_file_data(conn, raw_id)
    assert conn.execute("SELECT count(*) FROM positions").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM reception_gaps").fetchone() == (0,)
    db.mark_failed(conn, raw_id, "Testfehler")
    assert db.pending_files(conn) == [(raw_id, "TEST/2026/11/09/20261109T140000Z.ndjson.gz", "a" * 64)]


def test_status_view(conns, tmp_path):
    admin, conn = conns
    db.ensure_partitions(admin, T0, T0)
    db.load_parsed(conn, register(conn)[0], parsed_sample(tmp_path))
    row = conn.execute(
        "SELECT receiver_id, files_not_ingested, receiver_free_bytes FROM ingest_status"
    ).fetchone()
    assert row == ("TEST", 0, 999)
```

- [ ] **Step 2: Tests laufen lassen – müssen fehlschlagen**

Run: `pytest tests/db/test_load.py -v`
Expected: FAIL mit `AttributeError: module 'ingest.db' has no attribute 'ensure_partitions'`

- [ ] **Step 3: Implementierung – an `ingest/src/ingest/db.py` anhängen**

Imports am Dateianfang ergänzen:

```python
from datetime import UTC, datetime, timedelta

from psycopg import sql

from ingest.parse import POSITION_FIELDS, ParsedFile
```

Funktionen:

```python
def _month_start(ts: datetime) -> datetime:
    ts = ts.astimezone(UTC)
    return datetime(ts.year, ts.month, 1, tzinfo=UTC)


def _next_month(m: datetime) -> datetime:
    return datetime(m.year + m.month // 12, m.month % 12 + 1, 1, tzinfo=UTC)


def ensure_partitions(conn: psycopg.Connection, start: datetime, end: datetime) -> list[str]:
    """Legt fehlende Monatspartitionen von ``positions`` für [start, end] an (Admin-Rolle)."""
    created = []
    month = _month_start(start)
    while month <= end:
        nxt = _next_month(month)
        name = f"positions_y{month:%Y}m{month:%m}"
        if conn.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is None:
            conn.execute(
                sql.SQL("CREATE TABLE {} PARTITION OF positions FOR VALUES FROM ({}) TO ({})").format(
                    sql.Identifier(name), sql.Literal(month), sql.Literal(nxt)
                )
            )
            created.append(name)
        month = nxt
    return created


def ensure_receiver(conn: psycopg.Connection, receiver_id: str) -> None:
    conn.execute(
        "INSERT INTO receivers (id, label) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
        (receiver_id, receiver_id),
    )


def register_raw_file(
    conn: psycopg.Connection,
    *,
    receiver_id: str,
    path: str,
    sha256: str,
    size_bytes: int,
    partial: bool,
    version: str,
) -> tuple[int, str]:
    """Registriert eine Rohdatei; bei bekannter Prüfsumme wird der vorhandene Eintrag geliefert.

    Gleicher Pfad mit anderer Prüfsumme löst ``UniqueViolation`` aus.
    """
    row = conn.execute(
        """
        INSERT INTO raw_files (receiver_id, path, sha256, size_bytes, partial, status, ingest_version)
        VALUES (%s, %s, %s, %s, %s, 'registered', %s)
        ON CONFLICT (sha256) DO UPDATE SET sha256 = EXCLUDED.sha256
        RETURNING id, status
        """,
        (receiver_id, path, sha256, size_bytes, partial, version),
    ).fetchone()
    return row[0], row[1]


def find_raw_file(conn: psycopg.Connection, sha256: str) -> int | None:
    row = conn.execute("SELECT id FROM raw_files WHERE sha256 = %s", (sha256,)).fetchone()
    return None if row is None else row[0]


_TMP_COLUMNS = """
    ts timestamptz, icao24 text, callsign text, lon double precision, lat double precision,
    on_ground boolean, alt_baro_ft integer, alt_geom_ft integer, gs_kt real, track_deg real,
    baro_rate_fpm integer, squawk text, source_type text, nic smallint, nac_p smallint,
    sil smallint, rssi_dbfs real
"""

_INSERT_POSITIONS = """
    INSERT INTO positions (ts, receiver_id, icao24, callsign, geom, on_ground, alt_baro_ft,
        alt_geom_ft, gs_kt, track_deg, baro_rate_fpm, squawk, source_type, nic, nac_p, sil,
        rssi_dbfs, raw_file_id)
    SELECT ts, %(receiver_id)s, icao24, callsign, ST_SetSRID(ST_MakePoint(lon, lat), 4326),
        on_ground, alt_baro_ft, alt_geom_ft, gs_kt, track_deg, baro_rate_fpm, squawk,
        source_type, nic, nac_p, sil, rssi_dbfs, %(raw_file_id)s
    FROM tmp_positions
    ON CONFLICT DO NOTHING
"""

_UPSERT_AIRCRAFT = """
    INSERT INTO aircraft (icao24, registration, type_code, first_seen, last_seen)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (icao24) DO UPDATE SET
        registration = coalesce(EXCLUDED.registration, aircraft.registration),
        type_code = coalesce(EXCLUDED.type_code, aircraft.type_code),
        first_seen = least(aircraft.first_seen, EXCLUDED.first_seen),
        last_seen = greatest(aircraft.last_seen, EXCLUDED.last_seen)
"""


def load_parsed(conn: psycopg.Connection, raw_file_id: int, parsed: ParsedFile) -> int:
    """Lädt eine Datei in einer Transaktion; gibt die Zahl neu eingefügter Positionen zurück."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE tmp_positions ({_TMP_COLUMNS}) ON COMMIT DROP")
        with cur.copy(f"COPY tmp_positions ({', '.join(POSITION_FIELDS)}) FROM STDIN") as copy:
            for p in parsed.positions:
                copy.write_row(tuple(getattr(p, f) for f in POSITION_FIELDS))
        cur.execute(
            _INSERT_POSITIONS, {"receiver_id": parsed.receiver_id, "raw_file_id": raw_file_id}
        )
        inserted = cur.rowcount
        cur.executemany(
            "INSERT INTO reception_gaps (receiver_id, gap_start, gap_end, reason, raw_file_id)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(parsed.receiver_id, g.start, g.end, g.reason, raw_file_id) for g in parsed.gaps],
        )
        cur.executemany(
            _UPSERT_AIRCRAFT,
            [
                (a.icao24, a.registration, a.type_code, a.first_seen, a.last_seen)
                for a in parsed.aircraft.values()
            ],
        )
        cur.execute(
            """
            UPDATE raw_files SET status = 'ingested', error = NULL, period_start = %s,
                period_end = %s, clock_offset_max_s = %s, receiver_free_bytes = %s
            WHERE id = %s
            """,
            (
                parsed.period_start,
                parsed.period_end,
                parsed.clock_offset_max_s,
                parsed.receiver_free_bytes,
                raw_file_id,
            ),
        )
    return inserted


def mark_failed(conn: psycopg.Connection, raw_file_id: int, error: str) -> None:
    conn.execute(
        "UPDATE raw_files SET status = 'failed', error = %s WHERE id = %s", (error, raw_file_id)
    )


def pending_files(conn: psycopg.Connection) -> list[tuple[int, str, str]]:
    return conn.execute(
        "SELECT id, path, sha256 FROM raw_files"
        " WHERE status IN ('registered', 'failed') ORDER BY id"
    ).fetchall()


def delete_file_data(conn: psycopg.Connection, raw_file_id: int) -> None:
    """Entfernt Positionen und Lücken einer Datei (für ``rebuild``); Archiv bleibt unberührt."""
    start, end = conn.execute(
        "SELECT period_start, period_end FROM raw_files WHERE id = %s", (raw_file_id,)
    ).fetchone()
    with conn.transaction():
        if start is not None:
            # Positionszeitpunkte liegen um seen_pos vor recorder_ts; Puffer von 5 Minuten.
            conn.execute(
                "DELETE FROM positions WHERE raw_file_id = %s AND ts >= %s AND ts <= %s",
                (raw_file_id, start - timedelta(minutes=5), end),
            )
        conn.execute("DELETE FROM reception_gaps WHERE raw_file_id = %s", (raw_file_id,))
        conn.execute("UPDATE raw_files SET status = 'registered' WHERE id = %s", (raw_file_id,))
```

- [ ] **Step 4: Tests laufen lassen – müssen bestehen**

Run: `pytest tests/db -v && ruff check . && ruff format --check .`
Expected: alle DB-Tests PASS

- [ ] **Step 5: Commit**

```bash
git add ingest/src/ingest/db.py tests/db/test_load.py
git commit -m "ingest: Partitionen und idempotentes Laden per COPY"
```

---

### Task 9: ingest – Übertragung, Pipeline, CLI und Container

**Files:**
- Create: `ingest/src/ingest/config.py`, `logjson.py`, `guard.py`, `transfer.py`, `pipeline.py`, `cli.py`, `__main__.py`
- Create: `ingest/Dockerfile`
- Test: `tests/ingest/test_transfer.py`, `tests/ingest/test_guard.py`, `tests/db/test_pipeline.py`

**Interfaces:**
- Consumes: Tasks 6–8
- Produces:
  - `ingest.config.Config` (frozen): `admin_dsn, ingest_dsn, receiver_host, receiver_user: str`, `ssh_key_read, ssh_key_ack, work_dir, archive_dir, migrations_dir: Path`, `interval_s: int = 300`, `environment: str = "production"`; Eigenschaften `staging_dir`, `ack_dir`, `quarantine_dir`, `heartbeat_file`, `known_hosts`; `Config.from_env(env)`
  - Umgebungsvariablen: `INGEST_ADMIN_DSN`, `INGEST_DB_DSN`, `RECEIVER_HOST`, `RECEIVER_SSH_USER`, `INGEST_SSH_KEY_READ`, `INGEST_SSH_KEY_ACK`, `INGEST_WORK_DIR` (Standard `/work`), `RAW_ARCHIVE_DIR` (Standard `/archive`), `INGEST_MIGRATIONS_DIR` (Standard `/app/migrations`), `INGEST_INTERVAL_S`, `FLIGHTDB_ENV`
  - `ingest.guard.SyntheticDataRejected`, `check(parsed: ParsedFile, environment: str) -> None`
  - `ingest.transfer.TransferError`, `pull_command(cfg) -> list[str]`, `push_acks_command(cfg) -> list[str]`, `run(cmd: list[str]) -> None`
  - `ingest.pipeline.FileResult(rel: str, status: str, positions: int = 0, message: str = "")`; `process_file(cfg, admin, conn, staged: Path) -> FileResult`; `run_once(cfg, pull: bool = True) -> list[FileResult]`; `rebuild(cfg, start: datetime, end: datetime) -> list[FileResult]`; `file_start(name: str) -> datetime`
  - `python -m ingest {run|once|migrate|rebuild --from JJJJ-MM-TT --to JJJJ-MM-TT|health}`

- [ ] **Step 1: Failing Tests schreiben**

`tests/ingest/test_guard.py`:

```python
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
```

`tests/ingest/test_transfer.py`:

```python
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
```

`tests/db/test_pipeline.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from synthetic.generator import aircraft, snapshot
from synthetic.rawfiles import write_raw_file

from conftest import MIGRATIONS
from ingest.checksum import sha256_file
from ingest.config import Config
from ingest.pipeline import rebuild, run_once

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)


def make_cfg(tmp_path, dsns, environment="test"):
    return Config(
        admin_dsn=dsns["admin"],
        ingest_dsn=dsns["ingest"],
        receiver_host="unused",
        receiver_user="unused",
        ssh_key_read=Path("/unused"),
        ssh_key_ack=Path("/unused"),
        work_dir=tmp_path / "work",
        archive_dir=tmp_path / "archive",
        migrations_dir=MIGRATIONS,
        environment=environment,
    )


def stage(cfg, start=T0, n=3):
    snaps = [snapshot(start.timestamp() + i, [aircraft(lat=50 + i / 100)]) for i in range(n)]
    return write_raw_file(cfg.staging_dir, start, snaps)


def count(dsn, query):
    with psycopg.connect(dsn) as c:
        return c.execute(query).fetchone()[0]


def test_ingests_archives_and_acks(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns)
    staged = stage(cfg)
    rel = staged.relative_to(cfg.staging_dir)

    (result,) = run_once(cfg, pull=False)

    assert (result.status, result.positions) == ("ingested", 3)
    archived = cfg.archive_dir / rel
    assert archived.exists() and archived.with_name(archived.name + ".sha256").exists()
    assert not staged.exists()
    ack = cfg.ack_dir / rel.parent / (rel.name + ".ack")
    assert ack.read_text().strip() == sha256_file(archived)
    assert count(db_dsns["admin"], "SELECT count(*) FROM positions") == 3
    assert cfg.heartbeat_file.exists()


def test_same_file_again_is_skipped(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns)
    staged = stage(cfg)
    content = staged.read_bytes(), staged.with_name(staged.name + ".sha256").read_bytes()
    run_once(cfg, pull=False)
    staged.write_bytes(content[0])
    staged.with_name(staged.name + ".sha256").write_bytes(content[1])

    (result,) = run_once(cfg, pull=False)

    assert result.status == "skipped"
    assert count(db_dsns["admin"], "SELECT count(*) FROM positions") == 3


def test_corrupt_file_goes_to_quarantine(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns)
    staged = stage(cfg)
    staged.write_bytes(staged.read_bytes() + b"x")
    (result,) = run_once(cfg, pull=False)
    assert result.status == "quarantined"
    assert (cfg.quarantine_dir / staged.relative_to(cfg.staging_dir)).exists()
    assert not list(cfg.ack_dir.rglob("*.ack"))


def test_production_quarantines_synthetic(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns, environment="production")
    stage(cfg)
    (result,) = run_once(cfg, pull=False)
    assert result.status == "quarantined"
    assert "synthetisch" in result.message
    assert count(db_dsns["admin"], "SELECT count(*) FROM raw_files") == 0


def test_rebuild_reloads_from_archive(tmp_path, db_dsns):
    cfg = make_cfg(tmp_path, db_dsns)
    stage(cfg)
    run_once(cfg, pull=False)
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        c.execute("DELETE FROM positions WHERE ts > (SELECT min(ts) FROM positions)")

    results = rebuild(cfg, datetime(2026, 11, 9, tzinfo=UTC), datetime(2026, 11, 10, tzinfo=UTC))

    assert [r.status for r in results] == ["ingested"]
    assert count(db_dsns["admin"], "SELECT count(*) FROM positions") == 3
    assert count(db_dsns["admin"], "SELECT count(*) FROM raw_files") == 1
```

- [ ] **Step 2: Tests laufen lassen – müssen fehlschlagen**

Run: `pytest tests/ingest tests/db/test_pipeline.py -v`
Expected: FAIL mit `ModuleNotFoundError` für `ingest.guard`, `ingest.config`, `ingest.pipeline`

- [ ] **Step 3: Implementierung**

`ingest/src/ingest/config.py`:

```python
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
```

`ingest/src/ingest/logjson.py` – identisch zu `receiver/recorder/src/recorder/logjson.py` aus Task 5 (bewusst dupliziert: getrennt ausgelieferte Container ohne gemeinsames Paket):

```python
"""Strukturierte JSON-Logs nach stdout."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        out.update({k: v for k, v in vars(record).items() if k not in _STANDARD})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
```

`ingest/src/ingest/guard.py`:

```python
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
```

`ingest/src/ingest/transfer.py`:

```python
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
```

`ingest/src/ingest/pipeline.py`:

```python
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
    """Kopiert Datei und Prüfsumme unverändert ins Archiv, prüft die Kopie, entfernt das Original."""
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
```

`ingest/src/ingest/cli.py`:

```python
"""Kommandozeile: ``python -m ingest {run|once|migrate|rebuild|health}``."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

import psycopg

from ingest import __version__
from ingest.config import Config
from ingest.db import migrate
from ingest.logjson import setup_logging
from ingest.pipeline import rebuild, run_once

log = logging.getLogger("ingest")

HEALTH_MAX_AGE_S = 900


def _date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _migrate(cfg: Config) -> None:
    with psycopg.connect(cfg.admin_dsn, autocommit=True) as conn:
        for name in migrate(conn, cfg.migrations_dir):
            log.info("Migration eingespielt", extra={"migration": name})


def _health() -> int:
    work = Config.from_env().work_dir
    try:
        age = time.time() - (work / "heartbeat").stat().st_mtime
    except FileNotFoundError:
        return 1
    return 0 if age <= HEALTH_MAX_AGE_S else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Dauerbetrieb")
    sub.add_parser("once", help="ein Durchlauf")
    sub.add_parser("migrate", help="nur Migrationen einspielen")
    sub.add_parser("health", help="Healthcheck")
    rb = sub.add_parser("rebuild", help="Archiv neu einlesen")
    rb.add_argument("--from", dest="start", type=_date, required=True)
    rb.add_argument("--to", dest="end", type=_date, required=True)
    args = parser.parse_args(argv)

    if args.cmd == "health":
        return _health()

    setup_logging()
    cfg = Config.from_env()
    _migrate(cfg)
    if args.cmd == "migrate":
        return 0
    if args.cmd == "once":
        run_once(cfg)
        return 0
    if args.cmd == "rebuild":
        results = rebuild(cfg, args.start, args.end)
        log.info("rebuild beendet", extra={"files": len(results)})
        return 0 if all(r.status == "ingested" for r in results) else 1

    log.info("ingest gestartet", extra={"version": __version__, "interval_s": cfg.interval_s})
    while True:
        try:
            results = run_once(cfg)
            if results:
                log.info("Durchlauf beendet", extra={"files": len(results)})
        except Exception:
            log.exception("Durchlauf fehlgeschlagen")
        time.sleep(cfg.interval_s)


if __name__ == "__main__":
    sys.exit(main())
```

`ingest/src/ingest/__main__.py`:

```python
import sys

from ingest.cli import main

sys.exit(main())
```

`ingest/Dockerfile` (Build-Kontext: Repo-Wurzel):

```dockerfile
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends rsync openssh-client \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "psycopg[binary]==3.2.3" \
 && useradd -u 1000 -m ingest \
 && mkdir -p /work /archive && chown ingest:ingest /work /archive

WORKDIR /app
COPY ingest/src/ /app/
COPY database/migrations/ /app/migrations/
ENV PYTHONUNBUFFERED=1 INGEST_MIGRATIONS_DIR=/app/migrations

USER ingest
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD ["python", "-m", "ingest", "health"]
CMD ["python", "-m", "ingest", "run"]
```

- [ ] **Step 4: Tests laufen lassen – müssen bestehen**

Run: `pytest -v && ruff check . && ruff format --check .`
Expected: alle Tests PASS (DB-Tests mit gesetztem `TEST_ADMIN_DSN`).

- [ ] **Step 5: Image bauen (Smoke-Test)**

Run: `docker build -f ingest/Dockerfile -t flightdb-ingest:dev . && docker run --rm flightdb-ingest:dev python -m ingest --help`
Expected: Hilfe mit `{run,once,migrate,health,rebuild}`

- [ ] **Step 6: Commit**

```bash
git add ingest tests/ingest tests/db/test_pipeline.py
git commit -m "ingest: Abholung, Archivierung, Quittierung, rebuild und Container"
```

---

### Task 10: NAS – Compose, Backup, Deployment-Doku

**Files:**
- Create: `nas/docker-compose.yml`, `nas/.env.example`, `database/backup/backup.sh`, `docs/deployment-nas.md`
- Delete: `.env.example` (Wurzel)
- Modify: `README.md` (Link auf `.env.example` anpassen)

**Interfaces:**
- Consumes: `ingest/Dockerfile`, `database/init/10-roles.sh`, `database/migrations/`
- Produces: Stack `flightdb` mit Diensten `postgis`, `ingest`, `backup`; PostGIS im LAN auf Port `DB_LAN_PORT` (Standard 5433) für n8n/Grafana.

- [ ] **Step 1: Backup-Skript**

`database/backup/backup.sh`:

```bash
#!/bin/bash
# Nächtlicher pg_dump (Custom-Format) nach /dumps; behält die letzten BACKUP_KEEP Dumps.
# Aufruf mit --once für einen sofortigen Dump (Test/Restore-Probe).
set -euo pipefail

keep="${BACKUP_KEEP:-14}"
hour="${BACKUP_HOUR:-3}"

dump() {
  local f="/dumps/flightdb_$(date -u +%Y%m%dT%H%M%SZ).dump"
  pg_dump -Fc -f "$f.tmp"
  mv "$f.tmp" "$f"
  ls -1t /dumps/flightdb_*.dump | tail -n +"$((keep + 1))" | xargs -r rm --
  echo "{\"level\":\"info\",\"msg\":\"Backup erstellt\",\"file\":\"$f\"}"
}

if [[ "${1:-}" == "--once" ]]; then
  dump
  exit 0
fi

while true; do
  now=$(date +%s)
  next=$(date -d "today ${hour}:00" +%s)
  (( next <= now )) && next=$(date -d "tomorrow ${hour}:00" +%s)
  sleep $(( next - now ))
  dump || echo '{"level":"error","msg":"Backup fehlgeschlagen"}' >&2
done
```

Run: `chmod +x database/backup/backup.sh`

- [ ] **Step 2: Compose und Vorlage**

`nas/docker-compose.yml`:

```yaml
# Stack auf dem NAS. Start: docker compose --env-file .env up -d --build (im Ordner nas/)
name: flightdb

x-logging: &logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"

services:
  postgis:
    image: postgis/postgis:16-3.4
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      DB_INGEST_PASSWORD: ${DB_INGEST_PASSWORD}
      DB_READONLY_PASSWORD: ${DB_READONLY_PASSWORD}
      TZ: UTC
    volumes:
      - ${DB_DATA_DIR}:/var/lib/postgresql/data
      - ../database/init:/docker-entrypoint-initdb.d:ro
    ports:
      - "${DB_LAN_PORT:-5433}:5432"
    shm_size: 256mb
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
      timeout: 5s
      retries: 10
    logging: *logging

  ingest:
    build:
      context: ..
      dockerfile: ingest/Dockerfile
    restart: unless-stopped
    depends_on:
      postgis:
        condition: service_healthy
    environment:
      INGEST_ADMIN_DSN: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgis:5432/${POSTGRES_DB}
      INGEST_DB_DSN: postgresql://flightdb_ingest:${DB_INGEST_PASSWORD}@postgis:5432/${POSTGRES_DB}
      RECEIVER_HOST: ${RECEIVER_HOST}
      RECEIVER_SSH_USER: ${RECEIVER_SSH_USER}
      INGEST_SSH_KEY_READ: /ssh/ingest_read
      INGEST_SSH_KEY_ACK: /ssh/ingest_ack
      INGEST_INTERVAL_S: ${INGEST_INTERVAL_S:-300}
      FLIGHTDB_ENV: production
    volumes:
      - ${RAW_ARCHIVE_DIR}:/archive
      - ${INGEST_WORK_DIR}:/work
      - ${INGEST_SSH_DIR}:/ssh:ro
    logging: *logging

  backup:
    image: postgis/postgis:16-3.4
    restart: unless-stopped
    depends_on:
      postgis:
        condition: service_healthy
    entrypoint: ["/bin/bash", "/backup/backup.sh"]
    environment:
      PGHOST: postgis
      PGUSER: ${POSTGRES_USER}
      PGPASSWORD: ${POSTGRES_PASSWORD}
      PGDATABASE: ${POSTGRES_DB}
      BACKUP_KEEP: ${BACKUP_KEEP:-14}
      BACKUP_HOUR: ${BACKUP_HOUR:-3}
      TZ: Europe/Berlin
    volumes:
      - ../database/backup:/backup:ro
      - ${DB_BACKUP_DIR}:/dumps
    logging: *logging
```

`nas/.env.example`:

```bash
# Vorlage – kopieren nach nas/.env und ausfüllen. .env niemals committen.
# Passwörter nur aus Buchstaben und Ziffern (werden in Verbindungs-URLs verwendet).

# --- Datenbank ---
POSTGRES_DB=flightdb
POSTGRES_USER=flightdb_admin
POSTGRES_PASSWORD=change-me
DB_INGEST_PASSWORD=change-me
DB_READONLY_PASSWORD=change-me
DB_LAN_PORT=5433

# --- Speicherorte auf dem NAS (SSD für DB, HDD für Archiv und Backups) ---
DB_DATA_DIR=/volumeX/docker/flightdb/postgres
RAW_ARCHIVE_DIR=/volumeY/flightdb/raw
DB_BACKUP_DIR=/volumeY/flightdb/backups
INGEST_WORK_DIR=/volumeX/docker/flightdb/ingest-work
INGEST_SSH_DIR=/volumeX/docker/flightdb/ssh

# --- Empfangsstation ---
RECEIVER_HOST=receiver.local
RECEIVER_SSH_USER=flightdb-sync
INGEST_INTERVAL_S=300

# --- Backup ---
BACKUP_KEEP=14
BACKUP_HOUR=3
```

Run: `git rm .env.example` und in `README.md` den Satz `Konfiguration erfolgt über `.env` (Vorlage: [.env.example](.env.example)) und `config/local/`.` ersetzen durch: `Konfiguration erfolgt über `.env`-Dateien (Vorlagen: [nas/.env.example](nas/.env.example), [receiver/.env.example](receiver/.env.example)) und `config/local/`.`

- [ ] **Step 3: Compose lokal validieren**

```bash
cp nas/.env.example /tmp/nas.env
docker compose -f nas/docker-compose.yml --env-file /tmp/nas.env config --quiet && echo OK
```

Expected: `OK`

- [ ] **Step 4: Backup lokal testen**

```bash
docker compose -f tests/compose.test.yml up -d
docker run --rm --network host -e PGHOST=localhost -e PGPORT=55432 -e PGUSER=postgres \
  -e PGPASSWORD=test -e PGDATABASE=postgres -v "$PWD/database/backup:/backup:ro" \
  -v /tmp/flightdb-dumps:/dumps postgis/postgis:16-3.4 bash /backup/backup.sh --once
ls /tmp/flightdb-dumps
```

Expected: JSON-Zeile `Backup erstellt` und eine Datei `flightdb_…Z.dump`. (Auf macOS ohne `--network host`: `PGHOST=host.docker.internal`.)

- [ ] **Step 5: Deployment-Doku**

`docs/deployment-nas.md`:

````markdown
# Deployment auf dem NAS

Voraussetzung: Container Manager (DSM 7.2+), SSH-Zugang zum NAS für die Ersteinrichtung.
Bestehende Container (z. B. n8n) werden nicht verändert.

## 1. Verzeichnisse

Auf dem SSD-Volume: `docker/flightdb/postgres`, `docker/flightdb/ingest-work`, `docker/flightdb/ssh`.
Auf dem HDD-Volume: `flightdb/raw`, `flightdb/backups`.

```bash
sudo mkdir -p <ssd>/docker/flightdb/{postgres,ingest-work,ssh} <hdd>/flightdb/{raw,backups}
sudo chown 1000:1000 <ssd>/docker/flightdb/{ingest-work,ssh} <hdd>/flightdb/raw
sudo chown 999:999 <hdd>/flightdb/backups
```

(UID 999 = postgres im PostGIS-Image, UID 1000 = ingest.)

## 2. Repository und Konfiguration

Repository nach `<ssd>/docker/flightdb/repo` klonen, dann:

```bash
cd <ssd>/docker/flightdb/repo/nas
cp .env.example .env && chmod 600 .env   # Werte eintragen
```

## 3. SSH-Schlüssel für die Abholung

```bash
cd <ssd>/docker/flightdb/ssh
ssh-keygen -t ed25519 -N "" -C ingest-read -f ingest_read
ssh-keygen -t ed25519 -N "" -C ingest-ack  -f ingest_ack
sudo chown 1000:1000 ingest_read* ingest_ack* && sudo chmod 600 ingest_read ingest_ack
```

Die beiden `.pub`-Dateien werden auf dem Pi eingetragen (siehe `deployment-receiver.md`).

## 4. Start

```bash
cd <ssd>/docker/flightdb/repo/nas
sudo docker compose --env-file .env up -d --build
sudo docker compose ps
sudo docker compose logs -f ingest
```

Alternativ im Container Manager unter *Projekt → Erstellen* mit diesem Ordner.

## 5. Zugriff für n8n und Grafana

Verbindung zu `NAS-IP:${DB_LAN_PORT}`, Datenbank `flightdb`, Benutzer `flightdb_reader`.
Der Port ist nur im LAN freizugeben (DSM-Firewall), nicht ins Internet weiterleiten.

## 6. Prüfen

```bash
sudo docker compose exec postgis psql -U flightdb_admin -d flightdb -c "SELECT * FROM ingest_status"
```

## 7. Wiederherstellung

```bash
# Datenbank aus Dump:
sudo docker compose exec -T postgis pg_restore -U flightdb_admin -d flightdb --clean --if-exists \
  < <hdd>/flightdb/backups/flightdb_<zeit>.dump
# Oder komplett aus dem Rohdaten-Archiv neu aufbauen:
sudo docker compose run --rm ingest python -m ingest rebuild --from 2026-01-01 --to 2100-01-01
```
````

- [ ] **Step 6: Commit**

```bash
git add nas database/backup docs/deployment-nas.md README.md
git commit -m "NAS: Compose-Stack, Backup und Deployment-Anleitung"
```

---

### Task 11: Empfangsstation – Compose und Deployment-Doku

**Files:**
- Create: `receiver/docker-compose.yml`, `receiver/.env.example`, `docs/deployment-receiver.md`

**Interfaces:**
- Consumes: `receiver/recorder/Dockerfile`
- Produces: Stack auf dem Pi mit `ultrafeeder` (tar1090 auf Port 8080), `recorder`, `autoheal`; Feeder unter Profil `feeders`.

- [ ] **Step 1: Image-Digests ermitteln**

Für jedes Image den aktuellen Digest ermitteln und in Step 2 an der markierten Stelle als `@sha256:…` eintragen:

```bash
for img in ghcr.io/sdr-enthusiasts/docker-adsb-ultrafeeder:latest \
           ghcr.io/sdr-enthusiasts/docker-flightradar24:latest \
           ghcr.io/sdr-enthusiasts/docker-piaware:latest \
           ghcr.io/sdr-enthusiasts/docker-opensky-network:latest \
           willfarrell/autoheal:latest; do
  echo "$img $(docker buildx imagetools inspect "$img" --format '{{json .Manifest.Digest}}')"
done
```

Zusätzlich in den READMEs der Images (github.com/sdr-enthusiasts/…) die in Step 2 verwendeten Umgebungsvariablen gegenprüfen; Abweichungen in Compose und `.env.example` übernehmen und im Commit erwähnen.

- [ ] **Step 2: Compose und Vorlage**

`receiver/docker-compose.yml` (`<DIGEST>` durch die Werte aus Step 1 ersetzen):

```yaml
# Stack auf dem Raspberry Pi. Start: docker compose up -d --build (im Ordner receiver/)
# Feeder zusätzlich: docker compose --profile feeders up -d
name: receiver

x-logging: &logging
  driver: json-file
  options:
    max-size: "5m"
    max-file: "3"

services:
  ultrafeeder:
    image: ghcr.io/sdr-enthusiasts/docker-adsb-ultrafeeder:latest@sha256:<DIGEST>
    restart: unless-stopped
    device_cgroup_rules:
      - "c 189:* rwm"
    volumes:
      - /dev/bus/usb:/dev/bus/usb
      - ultrafeeder-globe:/var/globe_history
    tmpfs:
      - /run:exec,size=64M
      - /var/log:size=32M
    ports:
      - "8080:80"
    environment:
      TZ: UTC
      LOGLEVEL: error
      READSB_DEVICE_TYPE: rtlsdr
      READSB_RTLSDR_DEVICE: ${SDR_SERIAL}
      READSB_GAIN: autogain
      READSB_ENABLE_BIASTEE: ${SDR_BIASTEE:-false}
      READSB_LAT: ${FEEDER_LAT}
      READSB_LON: ${FEEDER_LON}
      READSB_ALT: ${FEEDER_ALT_M}m
      READSB_RX_LOCATION_ACCURACY: "2"
      READSB_STATS_RANGE: "true"
      UUID: ${ADSBLOL_UUID}
      MLAT_USER: ${FEEDER_NAME}
      ULTRAFEEDER_CONFIG: "adsb,feed.adsb.lol,30004,beast_reduce_plus_out;mlat,feed.adsb.lol,31090,39001"
    labels:
      autoheal: "true"
    logging: *logging

  recorder:
    build: ./recorder
    restart: unless-stopped
    user: "${RECORDER_UID}:${RECORDER_GID}"
    depends_on:
      - ultrafeeder
    environment:
      RECEIVER_ID: ${RECEIVER_ID}
      READSB_URL: http://ultrafeeder/data/aircraft.json
      RECORDER_DATA_DIR: /data
      RECEIVER_RETENTION_DAYS: ${RECEIVER_RETENTION_DAYS:-7}
      RECORDER_NTP_SERVER: ${RECORDER_NTP_SERVER:-pool.ntp.org}
    volumes:
      - ${RECORDER_DATA_DIR}:/data
    labels:
      autoheal: "true"
    logging: *logging

  autoheal:
    image: willfarrell/autoheal:latest@sha256:<DIGEST>
    restart: unless-stopped
    environment:
      AUTOHEAL_CONTAINER_LABEL: autoheal
      AUTOHEAL_INTERVAL: "30"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    logging: *logging

  fr24:
    image: ghcr.io/sdr-enthusiasts/docker-flightradar24:latest@sha256:<DIGEST>
    profiles: ["feeders"]
    restart: unless-stopped
    environment:
      BEASTHOST: ultrafeeder
      FR24KEY: ${FR24_KEY}
    logging: *logging

  piaware:
    image: ghcr.io/sdr-enthusiasts/docker-piaware:latest@sha256:<DIGEST>
    profiles: ["feeders"]
    restart: unless-stopped
    environment:
      TZ: UTC
      BEASTHOST: ultrafeeder
      RECEIVER_TYPE: relay
      LAT: ${FEEDER_LAT}
      LONG: ${FEEDER_LON}
      FEEDER_ID: ${PIAWARE_FEEDER_ID}
    tmpfs:
      - /run:exec,size=64M
      - /var/log
    logging: *logging

  opensky:
    image: ghcr.io/sdr-enthusiasts/docker-opensky-network:latest@sha256:<DIGEST>
    profiles: ["feeders"]
    restart: unless-stopped
    environment:
      BEASTHOST: ultrafeeder
      LAT: ${FEEDER_LAT}
      LONG: ${FEEDER_LON}
      ALT: ${FEEDER_ALT_M}
      OPENSKY_USERNAME: ${OPENSKY_USERNAME}
      OPENSKY_SERIAL: ${OPENSKY_SERIAL}
    tmpfs:
      - /run:exec,size=64M
      - /var/log
    logging: *logging

volumes:
  ultrafeeder-globe:
```

`receiver/.env.example`:

```bash
# Vorlage – kopieren nach receiver/.env und ausfüllen. .env niemals committen.
# Enthält den genauen Standort: Datei nur auf dem Pi, chmod 600.

RECEIVER_ID=rx1

# --- Standort der Antenne (WGS84, Höhe über NN in Metern) ---
FEEDER_LAT=
FEEDER_LON=
FEEDER_ALT_M=
FEEDER_NAME=

# --- SDR ---
SDR_SERIAL=
# true für RTL-SDR Blog V4 mit LNA an der Antenne
SDR_BIASTEE=false

# --- recorder ---
RECORDER_DATA_DIR=/srv/flightdb/data
RECORDER_UID=1000
RECORDER_GID=1000
RECEIVER_RETENTION_DAYS=7
RECORDER_NTP_SERVER=pool.ntp.org

# --- Einspeisung (Profil "feeders") ---
ADSBLOL_UUID=
FR24_KEY=
PIAWARE_FEEDER_ID=
OPENSKY_USERNAME=
OPENSKY_SERIAL=
```

- [ ] **Step 3: Compose validieren**

```bash
cp receiver/.env.example /tmp/rx.env
docker compose -f receiver/docker-compose.yml --env-file /tmp/rx.env --profile feeders config --quiet && echo OK
grep -c '<DIGEST>' receiver/docker-compose.yml
```

Expected: `OK` und `0` (alle Digests eingetragen).

- [ ] **Step 4: Deployment-Doku**

`docs/deployment-receiver.md`:

````markdown
# Deployment der Empfangsstation (Raspberry Pi)

## 1. Betriebssystem

- Raspberry Pi Imager: *Raspberry Pi OS Lite (64-bit)*, SSH mit Schlüssel, WLAN, Hostname setzen.
- Pufferspeicher bevorzugt auf USB-SSD, eingehängt unter `/srv/flightdb`.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y chrony rsync git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

## 2. DVB-Treiber sperren

Der Kernel-Treiber für DVB-T-Sticks blockiert das SDR für readsb:

```bash
printf 'blacklist dvb_usb_rtl28xxu\nblacklist rtl2832\nblacklist rtl2830\n' | \
  sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
sudo reboot
```

## 3. Benutzer, Gruppe und Datenverzeichnis

```bash
sudo groupadd -g 1000 flightdb 2>/dev/null || true   # GID muss RECORDER_GID entsprechen
sudo useradd -m -g flightdb -s /bin/sh flightdb-sync
sudo usermod -p '*' flightdb-sync                    # kein Passwort, nur Schlüssel
sudo mkdir -p /srv/flightdb/data/{current,complete,acked}
sudo chown -R 1000:flightdb /srv/flightdb/data
sudo chmod 2775 /srv/flightdb/data /srv/flightdb/data/{current,complete,acked}
```

Hinweis: Hat der Standardbenutzer des Pi bereits UID/GID 1000, `RECORDER_UID`/`RECORDER_GID`
in `.env` auf diese Werte setzen und `flightdb-sync` zusätzlich in diese Gruppe aufnehmen.

## 4. Zugang für das NAS

`/home/flightdb-sync/.ssh/authorized_keys` (Inhalt der beiden `.pub`-Dateien vom NAS):

```text
command="rrsync -ro /srv/flightdb/data/complete",restrict ssh-ed25519 AAAA… ingest-read
command="rrsync -wo /srv/flightdb/data/acked",restrict ssh-ed25519 AAAA… ingest-ack
```

```bash
sudo chown -R flightdb-sync:flightdb /home/flightdb-sync/.ssh
sudo chmod 700 /home/flightdb-sync/.ssh && sudo chmod 600 /home/flightdb-sync/.ssh/authorized_keys
which rrsync   # erwartet /usr/bin/rrsync
```

Test vom NAS: `ssh -i ingest_read flightdb-sync@<pi>` muss abgelehnt werden (keine Shell);
`rsync -e "ssh -i ingest_read" flightdb-sync@<pi>: /tmp/x/` muss funktionieren.

## 5. SDR prüfen und Stack starten

```bash
lsusb                                  # RTL2832U: 0bda:2838 oder 0bda:2832
git clone <repo-url> ~/flightdb && cd ~/flightdb/receiver
cp .env.example .env && chmod 600 .env  # Standort, SDR-Seriennummer, IDs eintragen
docker compose up -d --build
docker compose ps
```

Live-Karte im LAN: `http://<pi>:8080`.

## 6. Einspeisung

Nach Registrierung bei den Netzwerken (Schlüssel in `.env`):

```bash
docker compose --profile feeders up -d
```

Wo angeboten, öffentliche Standortanzeige auf „ungenau“ stellen.

## 7. Prüfen

```bash
docker compose logs -f recorder
ls -R /srv/flightdb/data/complete | tail
```
````

- [ ] **Step 5: Commit**

```bash
git add receiver/docker-compose.yml receiver/.env.example docs/deployment-receiver.md
git commit -m "Empfangsstation: Compose-Stack und Deployment-Anleitung"
```

---

### Task 12: End-to-End-Test

**Files:**
- Create: `tests/fixtures/synthetic/serve.py`, `tests/e2e/compose.yml`, `tests/e2e/receiver-ssh/Dockerfile`, `tests/e2e/receiver-ssh/entrypoint.sh`, `tests/e2e/test_e2e.py`
- Modify: `.github/workflows/ci.yml` (Job `e2e`)

**Interfaces:**
- Consumes: alle vorherigen Tasks
- Produces: `pytest -m e2e` prüft Pi-Simulation → rsync/rrsync → ingest → PostGIS inklusive Verbindungsunterbrechung.

- [ ] **Step 1: readsb-Attrappe**

`tests/fixtures/synthetic/serve.py`:

```python
"""readsb-Attrappe: liefert /data/aircraft.json mit drei synthetischen Flugzeugen (ff00xx)."""

from __future__ import annotations

import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from synthetic.generator import aircraft, snapshot


def current_snapshot(t: float) -> dict:
    planes = []
    for i in range(3):
        angle = (t / 120.0 + i * 2.1) % (2 * math.pi)
        planes.append(
            aircraft(
                hex=f"ff00{i:02x}",
                lat=50.0 + 0.2 * math.sin(angle),
                lon=10.0 + 0.3 * math.cos(angle),
                alt_baro=3000 + 1000 * i,
                seen_pos=0.4,
            )
        )
    return snapshot(round(t, 1), planes)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/data/aircraft.json":
            self.send_error(404)
            return
        body = json.dumps(current_snapshot(time.time())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()
```

- [ ] **Step 2: Simulierter Pi-SSH-Zugang**

`tests/e2e/receiver-ssh/Dockerfile`:

```dockerfile
FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-server rsync python3 procps \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 1000 flightdb \
 && useradd -m -u 1001 -g flightdb flightdb-sync \
 && usermod -p '*' flightdb-sync \
 && mkdir -p /run/sshd
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
HEALTHCHECK --interval=2s --retries=30 CMD test -f /keys/ingest_read && pgrep sshd
CMD ["/entrypoint.sh"]
```

`tests/e2e/receiver-ssh/entrypoint.sh`:

```bash
#!/bin/bash
# Simulierte Empfangsstation: Datenverzeichnis und SSH-Zugang wie auf dem echten Pi.
set -euo pipefail

mkdir -p /data/current /data/complete /data/acked
chown -R 1000:1000 /data
chmod 2775 /data /data/current /data/complete /data/acked

if [[ ! -f /keys/ingest_read ]]; then
  ssh-keygen -q -t ed25519 -N "" -C ingest-read -f /keys/ingest_read
  ssh-keygen -q -t ed25519 -N "" -C ingest-ack -f /keys/ingest_ack
fi
chown 1000:1000 /keys/ingest_read /keys/ingest_ack
chmod 600 /keys/ingest_read /keys/ingest_ack

install -d -m 700 -o flightdb-sync -g flightdb /home/flightdb-sync/.ssh
{
  echo "command=\"rrsync -ro /data/complete\",restrict $(cat /keys/ingest_read.pub)"
  echo "command=\"rrsync -wo /data/acked\",restrict $(cat /keys/ingest_ack.pub)"
} > /home/flightdb-sync/.ssh/authorized_keys
chown flightdb-sync:flightdb /home/flightdb-sync/.ssh/authorized_keys
chmod 600 /home/flightdb-sync/.ssh/authorized_keys

ssh-keygen -A
exec /usr/sbin/sshd -D -e
```

- [ ] **Step 3: Compose für den Test**

`tests/e2e/compose.yml`:

```yaml
name: flightdb-e2e

services:
  postgis:
    image: postgis/postgis:16-3.4
    platform: linux/amd64
    environment:
      POSTGRES_DB: flightdb
      POSTGRES_USER: flightdb_admin
      POSTGRES_PASSWORD: admin
      DB_INGEST_PASSWORD: ingest
      DB_READONLY_PASSWORD: reader
    volumes:
      - ../../database/init:/docker-entrypoint-initdb.d:ro
    ports:
      - "55433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U flightdb_admin -d flightdb"]
      interval: 2s
      retries: 60

  fake-readsb:
    image: python:3.12-slim
    working_dir: /fixtures
    command: ["python", "-m", "synthetic.serve"]
    volumes:
      - ../fixtures:/fixtures:ro

  receiver-ssh:
    build: ./receiver-ssh
    volumes:
      - receiver-data:/data
      - keys:/keys

  recorder:
    build: ../../receiver/recorder
    user: "1000:1000"
    depends_on:
      receiver-ssh:
        condition: service_healthy
      fake-readsb:
        condition: service_started
    environment:
      RECEIVER_ID: TEST
      READSB_URL: http://fake-readsb/data/aircraft.json
      RECORDER_DATA_DIR: /data
      RECORDER_ROTATE_SECONDS: "10"
      RECORDER_SYNTHETIC: "1"
      RECORDER_NTP_SERVER: 127.0.0.1
    volumes:
      - receiver-data:/data

  ingest:
    build:
      context: ../..
      dockerfile: ingest/Dockerfile
    depends_on:
      postgis:
        condition: service_healthy
      receiver-ssh:
        condition: service_healthy
    environment:
      INGEST_ADMIN_DSN: postgresql://flightdb_admin:admin@postgis:5432/flightdb
      INGEST_DB_DSN: postgresql://flightdb_ingest:ingest@postgis:5432/flightdb
      RECEIVER_HOST: receiver-ssh
      RECEIVER_SSH_USER: flightdb-sync
      INGEST_SSH_KEY_READ: /keys/ingest_read
      INGEST_SSH_KEY_ACK: /keys/ingest_ack
      INGEST_INTERVAL_S: "5"
      FLIGHTDB_ENV: test
    volumes:
      - keys:/keys:ro

volumes:
  receiver-data:
  keys:
```

- [ ] **Step 4: Test schreiben**

`tests/e2e/test_e2e.py`:

```python
import subprocess
import time
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.e2e

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parent / "compose.yml")]
DSN = "postgresql://flightdb_admin:admin@localhost:55433/flightdb"


@pytest.fixture(scope="module")
def stack():
    subprocess.run([*COMPOSE, "up", "-d", "--build"], check=True)
    try:
        yield
    finally:
        subprocess.run([*COMPOSE, "logs", "--no-color", "recorder", "ingest"], check=False)
        subprocess.run([*COMPOSE, "down", "-v"], check=True)


def query(sql):
    with psycopg.connect(DSN) as c:
        return c.execute(sql).fetchone()


def wait_for(condition, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if condition():
                return
        except psycopg.Error:
            pass
        time.sleep(3)
    pytest.fail("Zeitüberschreitung beim Warten")


def receiver_digests():
    out = subprocess.run(
        [*COMPOSE, "exec", "-T", "receiver-ssh", "sh", "-c",
         "find /data/complete -name '*.sha256' -exec cat {} +"],
        capture_output=True, text=True, check=True,
    ).stdout
    return {line.split()[0] for line in out.splitlines() if line.strip()}


def ingested_digests():
    with psycopg.connect(DSN) as c:
        return {r[0] for r in c.execute("SELECT sha256 FROM raw_files WHERE status = 'ingested'")}


def test_pipeline_end_to_end(stack):
    wait_for(lambda: query("SELECT count(*) FROM raw_files WHERE status = 'ingested'")[0] >= 3)

    total, distinct = query(
        "SELECT count(*), count(DISTINCT (receiver_id, icao24, ts)) FROM positions"
    )
    assert total > 0 and total == distinct
    assert query("SELECT count(DISTINCT icao24) FROM positions")[0] == 3
    assert query("SELECT count(*) FROM raw_files WHERE receiver_id <> 'TEST'")[0] == 0

    acks = subprocess.run(
        [*COMPOSE, "exec", "-T", "receiver-ssh", "find", "/data/acked", "-name", "*.ack"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert len(acks) >= 3


def test_connection_outage_loses_nothing(stack):
    subprocess.run([*COMPOSE, "stop", "receiver-ssh"], check=True)
    time.sleep(30)  # recorder schreibt weiter, ingest erreicht den Pi nicht
    subprocess.run([*COMPOSE, "start", "receiver-ssh"], check=True)

    expected = receiver_digests()
    assert len(expected) >= 5
    wait_for(lambda: expected <= ingested_digests())
```

- [ ] **Step 5: Test ausführen**

Run: `pytest -m e2e -v`
Expected: 2 passed (erster Lauf mit Image-Builds dauert einige Minuten).

Hinweis: Wird `receiver-ssh` gestoppt, verliert der recorder seinen Datenträger nicht (benanntes Volume), schreibt also weiter.

- [ ] **Step 6: E2E-Job in CI ergänzen – an `.github/workflows/ci.yml` anhängen**

```yaml
  e2e:
    runs-on: ubuntu-24.04
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements-dev.txt
      - run: pytest -m e2e -v
```

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/synthetic/serve.py tests/e2e .github/workflows/ci.yml
git commit -m "End-to-End-Test der Erfassungskette inkl. Verbindungsabbruch"
```

---

### Task 13: Dokumentation abschließen

**Files:**
- Create: `docs/data-model.md`
- Modify: `docs/architecture.md` (Abschnitt „Offene Punkte“, Verweise), `README.md` (Status, Dokumentationstabelle, Entwicklung)

- [ ] **Step 1: Datenmodell dokumentieren**

`docs/data-model.md`:

````markdown
# Datenmodell

Quelle der Wahrheit ist das Schema in `database/migrations/`. Dieses Dokument erklärt Bedeutung
und Herkunft der Daten.

## Rohdaten (Archiv)

`<receiver_id>/JJJJ/MM/TT/<JJJJMMTT>T<HHMMSS>Z[.partial].ndjson.gz` + `.sha256`.
Je Zeile ein JSON-Objekt mit `type`, `recorder_ts` (UTC), `receiver_id`, `recorder_version`:

| `type` | Inhalt |
|---|---|
| `snapshot` | `data`: unveränderte `aircraft.json` von readsb |
| `gap` | `from`, `to`, `reason` (`no_data`, `stale_data`, `recorder_restart`) |
| `clock` | `offset_s`: gemessene Uhrabweichung (oder `null`) |
| `status` | `free_bytes`, `free_ratio` des Pufferspeichers |

`.partial` kennzeichnet Dateien, deren Aufzeichnung unterbrochen wurde.

## Tabellen

| Tabelle | Bedeutung |
|---|---|
| `receivers` | Empfangsstationen mit Gültigkeitszeitraum der Konfiguration |
| `raw_files` | jede archivierte Rohdatei mit Prüfsumme, Zeitraum, Uhrabweichung, Status |
| `reception_gaps` | belegte Empfangslücken |
| `aircraft` | Flugzeuge (ICAO24) mit Kennzeichen/Typ laut readsb-Datenbank |
| `positions` | Positionen, monatlich partitioniert |

### `positions`

| Spalte | Einheit / Bedeutung |
|---|---|
| `ts` | Positionszeitpunkt UTC = `data.now − seen_pos`, auf 0,1 s gerundet |
| `geom` | WGS84-Punkt (lon, lat) |
| `alt_baro_ft` | barometrische Höhe in ft (Standardatmosphäre, **nicht** Höhe über Grund) |
| `alt_geom_ft` | geometrische Höhe (GNSS) in ft |
| `on_ground` | Flugzeug meldet „am Boden“ |
| `gs_kt`, `track_deg`, `baro_rate_fpm` | Grundgeschwindigkeit kt, Kurs über Grund °, Steigrate ft/min |
| `source_type` | readsb-Quelle (`adsb_icao`, `mlat`, `tisb_*`, …) |
| `nic`, `nac_p`, `sil` | ADS-B-Integritäts- und Genauigkeitsangaben |
| `rssi_dbfs` | Signalstärke |
| `raw_file_id` | Herkunft: Datensatz in `raw_files` |

## Herkunftskette

`positions.raw_file_id` → `raw_files.path` + `sha256` → Datei im Archiv → `.sha256`.
Jede Position ist damit auf eine unveränderte, prüfsummengesicherte Rohdatei zurückführbar.

## Rollen

`flightdb_admin` (Eigentümer), `flightdb_ingest` (schreibt), `flightdb_reader` (liest; n8n, Grafana).
````

- [ ] **Step 2: Architektur und README aktualisieren**

In `docs/architecture.md` den Abschnitt `## Offene Punkte` ersetzen durch:

```markdown
## Weiterführend

- Datenmodell: [data-model.md](data-model.md)
- Deployment: [deployment-nas.md](deployment-nas.md), [deployment-receiver.md](deployment-receiver.md)
- Design Meilenstein 2: [superpowers/specs/2026-11-09-meilenstein-2-empfang-speicherung-design.md](superpowers/specs/2026-11-09-meilenstein-2-empfang-speicherung-design.md)

## Offene Punkte

- Modell des vorhandenen Raspberry Pi und Eignung vorhandener DVB-T-Sticks
- Abnahme Meilenstein 2 mit echter Hardware (7 Tage Dauerbetrieb, Speicherbedarf messen)
```

In `README.md`:
- Status-Zeile Meilenstein 2 ändern zu: `- Meilenstein 2 – Empfang und Speicherung: Software fertig und getestet, Abnahme mit Hardware ausstehend`
- Dokumentationstabelle um drei Zeilen ergänzen:

```markdown
| [docs/data-model.md](docs/data-model.md) | Datenmodell und Herkunftskette |
| [docs/deployment-nas.md](docs/deployment-nas.md) | Installation auf dem NAS |
| [docs/deployment-receiver.md](docs/deployment-receiver.md) | Installation der Empfangsstation |
```

- Neuen Abschnitt vor `## Konfiguration und Datenschutz` einfügen:

````markdown
## Entwicklung

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
bash scripts/install-hooks.sh
docker compose -f tests/compose.test.yml up -d
export TEST_ADMIN_DSN=postgresql://postgres:test@localhost:55432/postgres
pytest            # Unit- und DB-Tests
pytest -m e2e     # End-to-End mit Docker
```

Tests verwenden ausschließlich synthetische Daten (Empfänger `TEST`, ICAO24 `ff…`).
````

- [ ] **Step 3: Gesamtprüfung**

```bash
pytest -v && pytest -m e2e -v && ruff check . && ruff format --check .
git status --short
```

Expected: alle Tests grün, ruff sauber, nur die Doku-Dateien geändert.

- [ ] **Step 4: Commit und Push**

```bash
git add docs README.md
git commit -m "Dokumentation: Datenmodell, Deployment, Status Meilenstein 2"
git log --format='%ae %ce' | sort -u    # nur noreply-Adresse
git push
```
