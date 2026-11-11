# Meilenstein 4 – Flugroutenvergleich: Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An- und Abflüge mit veröffentlichten Verfahren (SID/STAR) vergleichen: Rolle und Betriebsrichtung bestimmen, jeden Flug mit Sicherheitsstufe und Begründung einem Verfahren zuordnen und Abweichungen (C), Annäherungen (B) und Prüffälle (E) nachvollziehbar ausweisen.

**Architecture:** Zusätzlicher Schritt im bestehenden Dienst `analysis` (gleicher Lauf, gleiche Transaktion, Savepoint je Flugzeug bzw. je Flug). Verfahren kommen aus der lokalen YAML-Datei `config/local/procedures.yaml` und werden wie Zonen versioniert in `procedures` gespeichert. Gerechnet wird in Python auf einer lokalen mittabstandstreuen Ebene um den BER-Referenzpunkt; Ergebnisse stehen in `operating_directions` und `flight_assessments` (Migration `003_routen.sql`, eingespielt von `ingest`). Grafana zeigt sie im neuen Dashboard „Flugrouten“ und in „Flugspur“.

**Tech Stack:** Python 3.12, psycopg 3.2.3, PyYAML 6.0.2, PostgreSQL 16 + PostGIS 3.4, Grafana 13.2.6, Docker Compose, pytest 8.3.3, ruff 0.7.4.

Spezifikation: [2026-11-11-meilenstein-4-flugroutenvergleich-design.md](../specs/2026-11-11-meilenstein-4-flugroutenvergleich-design.md)

## Global Constraints

- Öffentliches Repo: keine echten Koordinaten, Ortsnamen des Wohnumfelds, Hostnamen, IPs, Zugangsdaten. Testdaten nur synthetisch (Empfänger `TEST`, ICAO24 `ff…`, Rufzeichen `TST…`, Orte um 50,0° N / 10,0° O oder im Atlantik). Einzige reale Koordinate bleibt der öffentliche BER-Referenzpunkt in `nas/.env.example`.
- Verfahren: echte Verfahren nur in `config/local/procedures.yaml` (gitignored, Urheberrecht DFS). Im Repo nur `config/procedures.example.yaml` (erfundener Flughafen im Atlantik) und `tests/fixtures/procedures.test.yaml` (erfundener Flughafen um 50° N / 10° O). Keine realen Verfahrensnamen.
- Logs, Fehlermeldungen und Prüfausgaben ohne Koordinaten; Meldungen zur Verfahrensdatei nennen Eintrag und Feld.
- Commits: Autor ausschließlich der Repo-Inhaber (noreply-Adresse), **keine** `Co-Authored-By`- oder „Generated with“-Zeilen. Pre-Commit-Hook bleibt aktiv.
- Einheiten wie M2: Höhen ft, Geschwindigkeit kt, Raten ft/min, Abstände m, Zeiten UTC (`timestamptz`).
- Migrationen spielt nur `ingest` ein (alle `database/migrations/*.sql` in Namensreihenfolge, siehe `ingest/src/ingest/db.py`); `analysis` hat keine Admin-Rechte.
- Weiter gültig aus M3: Relevanzgrenze Standard 10000 ft; Pausenschwelle 600 s; Ausreißer > 800 kt; Kontext 120 s; mind. 5 Positionen; Vertikalrate 300 ft/min; BER-Radius 40000 m; Settle 120 s.
- Neue Parameter (Standardwerte wörtlich aus der Spezifikation): `ANALYSIS_PROCEDURES_FILE`, `ANALYSIS_ROLE_NEAR_M` (10000), `ANALYSIS_ROLE_MAX_ALT_FT` (3000), `ANALYSIS_DIRECTION_DIST_M` (15000), `ANALYSIS_DIRECTION_TOL_DEG` (30), `ANALYSIS_DIRECTION_MIN_FLIGHTS` (3), `ANALYSIS_DIRECTION_MIN_SHARE` (0.8), `ANALYSIS_ASSIGN_RATIO` (2.0), `ANALYSIS_ROUTE_MAX_ALT_FT` (leer), `ANALYSIS_CORRIDOR_M` (1852), `ANALYSIS_CORRIDOR_MIN_S` (30), `ANALYSIS_APPROACH_TOL_M` (= Korridor), `ANALYSIS_REVIEW_MAX_GAP_S` (30). Jeder Parameter steht in `config.py`, `nas/docker-compose.yml` (mit Standard), `docs/analysis.md` (Abschnitt Parameter) und in `analysis_runs.params`.
- Betriebsrichtung je 30-Minuten-Fenster (UTC, auf :00/:30 ausgerichtet): `west` (Kurs 180–359°), `east` (0–179°), `unknown`. Sicherheitsstufen `high`/`medium`/`low`/`none`. Wegpunkte höchstens 200 km vom BER-Referenzpunkt.
- `analysis.__version__` = `0.3.0`.
- Abhängigkeit neu: `PyYAML==6.0.2` (exakt gepinnt in `requirements-dev.txt` und `analysis/Dockerfile`).
- Grafana `grafana/grafana:13.2.6@sha256:b21409d7951ddcfd63a4b49083e4ef2cc35bc1437d071813bf82bfb238b00bca`, Datenquellen-UID `flightdb`, Typ `grafana-postgresql-datasource`.
- Dashboards ohne Kartenmittelpunkt/Zoom; Geomap-Ansicht `fit`; `scripts/check_dashboards.py` bleibt in der CI.
- ruff: line-length 100, Regeln E, F, I, B, UP; vor jedem Commit `ruff format .` und `ruff check .`.
- Testbefehle (lokal): `. .venv/bin/activate`, `pip install -r requirements-dev.txt` (nach Task 4), `docker compose -f tests/compose.test.yml up -d`, `export TEST_ADMIN_DSN=postgresql://postgres:test@localhost:55432/postgres`. Colima mountet nur `~`: keine Test-Volumes unter `/tmp`.
- Testdateinamen müssen projektweit eindeutig sein (kein `__init__.py` in `tests/`).

## Dateiübersicht

| Datei | Verantwortung |
|---|---|
| `database/migrations/003_routen.sql` | Tabellen `procedures`, `operating_directions`, `flight_assessments`, View `route_stats_daily`, Rechte |
| `analysis/src/analysis/config.py` | neue Parameter |
| `analysis/src/analysis/geo.py` | lokale Ebene um BER, Kurs, Austrittspunkt, Lotfußpunkt (rein) |
| `analysis/src/analysis/procedures.py` | Verfahrensdatei lesen und prüfen, Geometrie, Abgleich mit `procedures` |
| `analysis/src/analysis/role.py` | Rolle Abflug/Anflug (rein) |
| `analysis/src/analysis/direction.py` | Stimme je Flug, Betriebsrichtung je Fenster (rein) |
| `analysis/src/analysis/deviation.py` | Geltungsabschnitt, Korridor (C), Annäherung (B), Prüffall (E) (rein) |
| `analysis/src/analysis/assign.py` | Zuordnung Flug → Verfahren mit Sicherheitsstufe (rein) |
| `analysis/src/analysis/routes.py` | Ablauf und Datenbankzugriffe des Routenschritts |
| `analysis/src/analysis/pipeline.py`, `cli.py` | Einbindung in den Lauf, Befehl `procedures` |
| `config/procedures.example.yaml` | Beispieldatei (Atlantik) |
| `scripts/check_procedures.py` | Offline-Prüfung der Verfahrensdatei |
| `dashboard/build_dashboards.py` | Dashboard „Flugrouten“, Erweiterung „Flugspur“ |
| `tests/fixtures/procedures.test.yaml` | erfundener Testflughafen um 50° N / 10° O |
| `tests/fixtures/synthetic/routes.py` | synthetische An- und Abflüge in der lokalen Ebene |
| `tests/fixtures/synthetic/serve.py` | readsb-Attrappe fliegt zusätzlich An- und Abflüge |
| `docs/routes.md`, `docs/decisions/0007-zuordnung-zu-flugverfahren.md` | Methodik, Übertragen aus der AIP, Entscheidung |

**Testflughafen** (`tests/fixtures/procedures.test.yaml`, lokale Ebene in m, x Ost, y Nord um 50,0° N / 10,0° O): Schwellen `27` (1500, 0) und `09` (−1500, 0), Startbahnkurs 270° bzw. 90°. Wegpunkte `TWEST` (−16000, 0), `TEAST` (16000, 0), `WNMID` (−20000, 20000), `WNORD` (−35000, 40000), `WSMID` (−20000, −20000), `WSUED` (−35000, −40000), `ONMID` (20000, 20000), `ONORD` (35000, 40000), `OSMID` (20000, −20000), `OSUED` (35000, −40000). Je Betriebsrichtung zwei SIDs und zwei STARs; die ersten 16 km verlaufen geradeaus, damit der Bezugskurs (10–15 km) dem Startbahnkurs entspricht.

---

### Task 1: Datenbankschema `003_routen.sql`

**Files:**
- Create: `database/migrations/003_routen.sql`
- Modify: `tests/db/test_schema.py`

**Interfaces:**
- Produces: Tabellen `procedures`, `operating_directions`, `flight_assessments`; View `route_stats_daily`; Rechte für `flightdb_analysis` (Schreiben) und `flightdb_reader` (Lesen).

Zusätzlich zur Spezifikation (4.1, 4.3) und für den Ablauf nötig: `procedures.runway_heading_deg` (Startbahnkurs für die Stimme der Betriebsrichtung, auch wenn eine spätere Datei ungültig ist), `flight_assessments.ref_ts` (Bezugszeitpunkt, bestimmt das Fenster), `ref_heading_deg` (Bezugskurs) und `vote` (Stimme des Flugs). `ingest` spielt die neue Datei ohne Codeänderung ein: `migrate()` liest alle `*.sql` in Namensreihenfolge, das Image kopiert `database/migrations/`.

- [ ] **Step 1: Tests schreiben** – in `tests/db/test_schema.py` die Versionsliste in `test_migrate_is_idempotent` ersetzen durch:

```python
        assert versions == ["001_erfassung.sql", "002_analyse.sql", "003_routen.sql"]
```

und am Dateiende anhängen:

```python
def test_reader_reads_route_tables(db_dsns):
    with psycopg.connect(db_dsns["reader"]) as c:
        for name in (
            "procedures",
            "operating_directions",
            "flight_assessments",
            "route_stats_daily",
        ):
            c.execute(f"SELECT * FROM {name} LIMIT 1")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM procedures")


def test_operating_direction_window_is_aligned(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c:
        run = c.execute(
            "INSERT INTO analysis_runs (kind, algo_version, params, status)"
            " VALUES ('incremental', 'test', '{}', 'ok') RETURNING id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO operating_directions (window_start, direction, n_flights, basis, run_id)"
            " VALUES ('2026-11-09T14:30:00Z', 'west', 3, 'x', %s)",
            (run,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO operating_directions (window_start, direction, n_flights, basis,"
                " run_id) VALUES ('2026-11-09T14:10:00Z', 'west', 3, 'x', %s)",
                (run,),
            )
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/db/test_schema.py -v`
Expected: FAIL (`003_routen.sql` fehlt in der Liste, `relation "procedures" does not exist`).

- [ ] **Step 3: Migration schreiben** – `database/migrations/003_routen.sql`:

```sql
-- Meilenstein 4: Flugverfahren, Betriebsrichtung und Bewertung von An- und Abflügen.
-- Einheiten wie in 001/002: ft, kt, ft/min; Abstände in m; Zeiten in UTC.

CREATE TABLE procedures (
  id                  bigserial PRIMARY KEY,
  name                text NOT NULL,
  kind                text NOT NULL CHECK (kind IN ('SID', 'STAR')),
  runway              text NOT NULL,
  runway_heading_deg  real NOT NULL,
  direction           text NOT NULL CHECK (direction IN ('west', 'east')),
  sector              text NOT NULL,
  airac               text,
  valid_from          date NOT NULL,
  valid_to            date,
  source              text,
  geom                geometry(LineString, 4326) NOT NULL,
  waypoints           jsonb NOT NULL,
  constraints         jsonb NOT NULL DEFAULT '{}',
  content_hash        text NOT NULL,
  loaded_at           timestamptz NOT NULL DEFAULT now(),
  superseded_at       timestamptz,
  CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE UNIQUE INDEX procedures_current ON procedures (name, valid_from)
  WHERE superseded_at IS NULL;

CREATE TABLE operating_directions (
  window_start  timestamptz PRIMARY KEY
                CHECK (extract(epoch FROM window_start)::bigint % 1800 = 0),
  direction     text NOT NULL CHECK (direction IN ('west', 'east', 'unknown')),
  n_flights     integer NOT NULL,
  share         real,
  basis         text NOT NULL,
  run_id        bigint NOT NULL REFERENCES analysis_runs (id)
);

CREATE TABLE flight_assessments (
  flight_id           bigint PRIMARY KEY REFERENCES flights (id) ON DELETE CASCADE,
  run_id              bigint NOT NULL REFERENCES analysis_runs (id),
  role                text NOT NULL CHECK (role IN ('departure', 'arrival')),
  ref_ts              timestamptz NOT NULL,
  ref_heading_deg     real,
  vote                text CHECK (vote IN ('west', 'east')),
  direction           text CHECK (direction IN ('west', 'east', 'unknown')),
  flight_sector       text NOT NULL,
  procedure_id        bigint REFERENCES procedures (id),
  confidence          text NOT NULL CHECK (confidence IN ('high', 'medium', 'low', 'none')),
  basis               text NOT NULL,
  mean_dev_m          real,
  second_mean_dev_m   real,
  eval_from           timestamptz,
  eval_to             timestamptz,
  max_dev_m           real,
  outside_s           real,
  outside_m           real,
  deviation           boolean NOT NULL DEFAULT false,
  ref_geofence_id     bigint REFERENCES geofences (id),
  min_dist_ref_m      real,
  proc_dist_ref_m     real,
  approach            boolean NOT NULL DEFAULT false,
  review              boolean NOT NULL DEFAULT false,
  review_reasons      text[] NOT NULL DEFAULT '{}',
  in_reception_gap    boolean,
  max_position_gap_s  real
);

CREATE INDEX flight_assessments_ref_ts ON flight_assessments (ref_ts);
CREATE INDEX flight_assessments_procedure ON flight_assessments (procedure_id);

-- Tage in Europe/Berlin; Verfahren über den Namen, damit alle Fassungen zählen.
CREATE VIEW route_stats_daily AS
SELECT
  (a.ref_ts AT TIME ZONE 'Europe/Berlin')::date AS day,
  p.name AS procedure,
  a.confidence,
  count(*) AS n_flights,
  count(*) FILTER (WHERE a.deviation) AS n_deviations,
  count(*) FILTER (WHERE a.approach) AS n_approaches,
  count(*) FILTER (WHERE a.review) AS n_reviews,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY a.max_dev_m) AS median_max_dev_m,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY a.max_dev_m) AS p95_max_dev_m
FROM flight_assessments a
LEFT JOIN procedures p ON p.id = a.procedure_id
GROUP BY 1, 2, 3;

GRANT SELECT, INSERT, UPDATE, DELETE
  ON procedures, operating_directions, flight_assessments TO flightdb_analysis;
GRANT USAGE ON SEQUENCE procedures_id_seq TO flightdb_analysis;
GRANT SELECT ON procedures, operating_directions, flight_assessments, route_stats_daily
  TO flightdb_reader;
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/db -v`
Expected: alle PASS (inkl. der bestehenden Tests).

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add database/migrations/003_routen.sql tests/db/test_schema.py
git commit -m "Datenbank: Schema für Verfahren, Betriebsrichtung und Bewertung"
```

---

### Task 2: Parameter des Routenvergleichs

**Files:**
- Modify: `analysis/src/analysis/config.py` (ersetzen)
- Modify: `nas/docker-compose.yml`, `nas/.env.example`, `docs/analysis.md` (Abschnitt Parameter)
- Modify: `tests/analysis/test_analysis_config.py`, `tests/analysis/test_analysis_compose_env.py` (ersetzen)

**Interfaces:**
- Produces: `Config` mit neuen Feldern `procedures_file: Path | None`, `role_near_m: float`, `role_max_alt_ft: int`, `direction_dist_m: float`, `direction_tol_deg: float`, `direction_min_flights: int`, `direction_min_share: float`, `assign_ratio: float`, `route_max_alt_ft: int | None`, `corridor_m: float`, `corridor_min_s: float`, `approach_tol_m: float | None`, `review_max_gap_s: float`; Eigenschaft `Config.approach_tol -> float` (leer = `corridor_m`); `Config.params()` enthält alle neuen Werte (Pfade als Text, `approach_tol` als wirksamer Wert).

Leere Umgebungsvariablen (`ANALYSIS_ROUTE_MAX_ALT_FT=`, `ANALYSIS_APPROACH_TOL_M=`) gelten als nicht gesetzt; so kann `nas/docker-compose.yml` sie mit leerem Standard durchreichen.

- [ ] **Step 1: Tests schreiben** – in `tests/analysis/test_analysis_config.py` in `test_from_env_defaults` nach der letzten `assert`-Zeile ergänzen:

```python
    assert cfg.procedures_file is None
    assert (cfg.corridor_m, cfg.approach_tol, cfg.route_max_alt_ft) == (1852.0, 1852.0, None)
```

und am Dateiende anhängen:

```python
def test_route_parameters():
    cfg = Config.from_env(
        {
            "ANALYSIS_DB_DSN": "postgresql://x",
            "ANALYSIS_BER_LAT": "49.5",
            "ANALYSIS_BER_LON": "8.5",
            "ANALYSIS_PROCEDURES_FILE": "/zones/procedures.yaml",
            "ANALYSIS_CORRIDOR_M": "1000",
            "ANALYSIS_ROUTE_MAX_ALT_FT": "6000",
            "ANALYSIS_APPROACH_TOL_M": "",
        }
    )
    assert (cfg.corridor_m, cfg.approach_tol, cfg.route_max_alt_ft) == (1000.0, 1000.0, 6000)
    params = cfg.params()
    assert params["procedures_file"] == "/zones/procedures.yaml"
    assert (params["approach_tol"], params["direction_min_share"]) == (1000.0, 0.8)
    assert {"role_near_m", "assign_ratio", "corridor_min_s", "review_max_gap_s"} <= set(params)
```

`tests/analysis/test_analysis_compose_env.py` ersetzen durch (feste Containerpfade und leere Standards zulassen):

```python
"""Der NAS-Stack reicht alle dokumentierten ANALYSIS_*-Variablen mit passendem Standard durch."""

import re
from pathlib import Path

from analysis.config import Config

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {"ANALYSIS_DB_DSN", "ANALYSIS_BER_LAT", "ANALYSIS_BER_LON"}
# Feste Pfade im Container, kein Standardwert über .env
FIXED = {"ANALYSIS_ZONES_FILE", "ANALYSIS_PROCEDURES_FILE"}


def _documented() -> set[str]:
    text = (ROOT / "docs" / "analysis.md").read_text(encoding="utf-8")
    section = text.split("## Parameter", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"`(ANALYSIS_[A-Z_]+)`", section))


def _compose() -> str:
    return (ROOT / "nas" / "docker-compose.yml").read_text(encoding="utf-8")


def _compose_defaults() -> dict[str, str]:
    # Leerer Standard (``${X:-}``) bedeutet „nicht gesetzt“.
    return dict(re.findall(r"(ANALYSIS_[A-Z_]+): \$\{\1:-([^}]*)\}", _compose()))


def test_compose_passes_documented_analysis_vars():
    passed = set(re.findall(r"^\s+(ANALYSIS_[A-Z_]+):", _compose(), re.M))
    assert _documented() - passed == set()
    missing = _documented() - REQUIRED - FIXED - set(_compose_defaults())
    assert missing == set()


def test_compose_defaults_match_config():
    base = {"ANALYSIS_DB_DSN": "x", "ANALYSIS_BER_LAT": "0", "ANALYSIS_BER_LON": "0"}
    defaults = _compose_defaults()
    assert defaults
    assert Config.from_env(base) == Config.from_env(base | defaults)
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_analysis_config.py tests/analysis/test_analysis_compose_env.py -v`
Expected: FAIL (`AttributeError: 'Config' object has no attribute 'procedures_file'`).

- [ ] **Step 3: Implementierung** – `analysis/src/analysis/config.py` ersetzen durch:

```python
"""Konfiguration aus Umgebungsvariablen."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Werte, die das Ergebnis beeinflussen; werden je Lauf in analysis_runs.params festgehalten.
PARAM_FIELDS = (
    "settle_s",
    "flight_gap_s",
    "max_speed_kt",
    "context_s",
    "min_positions",
    "vrate_fpm",
    "ber_radius_m",
    "ber_lat",
    "ber_lon",
    "procedures_file",
    "role_near_m",
    "role_max_alt_ft",
    "direction_dist_m",
    "direction_tol_deg",
    "direction_min_flights",
    "direction_min_share",
    "assign_ratio",
    "route_max_alt_ft",
    "corridor_m",
    "corridor_min_s",
    "approach_tol",
    "review_max_gap_s",
)


def _optional(value: str | None, kind):
    return kind(value) if value else None


@dataclass(frozen=True)
class Config:
    db_dsn: str
    ber_lat: float
    ber_lon: float
    zones_file: Path | None = None
    procedures_file: Path | None = None
    interval_s: int = 300
    settle_s: int = 120
    flight_gap_s: int = 600
    max_speed_kt: float = 800.0
    context_s: int = 120
    min_positions: int = 5
    vrate_fpm: float = 300.0
    ber_radius_m: float = 40000.0
    default_relevance_ft: int = 10000
    max_lag_s: int = 10800
    heartbeat_file: Path = Path("/tmp/analysis-heartbeat")
    role_near_m: float = 10000.0
    role_max_alt_ft: int = 3000
    direction_dist_m: float = 15000.0
    direction_tol_deg: float = 30.0
    direction_min_flights: int = 3
    direction_min_share: float = 0.8
    assign_ratio: float = 2.0
    route_max_alt_ft: int | None = None
    corridor_m: float = 1852.0
    corridor_min_s: float = 30.0
    approach_tol_m: float | None = None  # leer: wie corridor_m
    review_max_gap_s: float = 30.0

    @property
    def approach_tol(self) -> float:
        return self.corridor_m if self.approach_tol_m is None else self.approach_tol_m

    def params(self) -> dict:
        values = {name: getattr(self, name) for name in PARAM_FIELDS}
        return {k: str(v) if isinstance(v, Path) else v for k, v in values.items()}

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        return cls(
            db_dsn=env["ANALYSIS_DB_DSN"],
            ber_lat=float(env["ANALYSIS_BER_LAT"]),
            ber_lon=float(env["ANALYSIS_BER_LON"]),
            zones_file=_optional(env.get("ANALYSIS_ZONES_FILE"), Path),
            procedures_file=_optional(env.get("ANALYSIS_PROCEDURES_FILE"), Path),
            interval_s=int(env.get("ANALYSIS_INTERVAL_S", "300")),
            settle_s=int(env.get("ANALYSIS_SETTLE_S", "120")),
            flight_gap_s=int(env.get("ANALYSIS_FLIGHT_GAP_S", "600")),
            max_speed_kt=float(env.get("ANALYSIS_MAX_SPEED_KT", "800")),
            context_s=int(env.get("ANALYSIS_CONTEXT_S", "120")),
            min_positions=int(env.get("ANALYSIS_MIN_POSITIONS", "5")),
            vrate_fpm=float(env.get("ANALYSIS_VRATE_FPM", "300")),
            ber_radius_m=float(env.get("ANALYSIS_BER_RADIUS_M", "40000")),
            default_relevance_ft=int(env.get("ANALYSIS_DEFAULT_RELEVANCE_FT", "10000")),
            max_lag_s=int(env.get("ANALYSIS_MAX_LAG_S", "10800")),
            heartbeat_file=Path(env.get("ANALYSIS_HEARTBEAT_FILE", "/tmp/analysis-heartbeat")),
            role_near_m=float(env.get("ANALYSIS_ROLE_NEAR_M", "10000")),
            role_max_alt_ft=int(env.get("ANALYSIS_ROLE_MAX_ALT_FT", "3000")),
            direction_dist_m=float(env.get("ANALYSIS_DIRECTION_DIST_M", "15000")),
            direction_tol_deg=float(env.get("ANALYSIS_DIRECTION_TOL_DEG", "30")),
            direction_min_flights=int(env.get("ANALYSIS_DIRECTION_MIN_FLIGHTS", "3")),
            direction_min_share=float(env.get("ANALYSIS_DIRECTION_MIN_SHARE", "0.8")),
            assign_ratio=float(env.get("ANALYSIS_ASSIGN_RATIO", "2.0")),
            route_max_alt_ft=_optional(env.get("ANALYSIS_ROUTE_MAX_ALT_FT"), int),
            corridor_m=float(env.get("ANALYSIS_CORRIDOR_M", "1852")),
            corridor_min_s=float(env.get("ANALYSIS_CORRIDOR_MIN_S", "30")),
            approach_tol_m=_optional(env.get("ANALYSIS_APPROACH_TOL_M"), float),
            review_max_gap_s=float(env.get("ANALYSIS_REVIEW_MAX_GAP_S", "30")),
        )
```

- [ ] **Step 4: NAS-Stack, Vorlage und Doku**

In `nas/docker-compose.yml` beim Dienst `analysis` die Zeile `      ANALYSIS_ZONES_FILE: /zones/geofences.geojson` ersetzen durch:

```yaml
      # Flugroutenvergleich (docs/routes.md)
      ANALYSIS_ROLE_NEAR_M: ${ANALYSIS_ROLE_NEAR_M:-10000}
      ANALYSIS_ROLE_MAX_ALT_FT: ${ANALYSIS_ROLE_MAX_ALT_FT:-3000}
      ANALYSIS_DIRECTION_DIST_M: ${ANALYSIS_DIRECTION_DIST_M:-15000}
      ANALYSIS_DIRECTION_TOL_DEG: ${ANALYSIS_DIRECTION_TOL_DEG:-30}
      ANALYSIS_DIRECTION_MIN_FLIGHTS: ${ANALYSIS_DIRECTION_MIN_FLIGHTS:-3}
      ANALYSIS_DIRECTION_MIN_SHARE: ${ANALYSIS_DIRECTION_MIN_SHARE:-0.8}
      ANALYSIS_ASSIGN_RATIO: ${ANALYSIS_ASSIGN_RATIO:-2.0}
      ANALYSIS_ROUTE_MAX_ALT_FT: ${ANALYSIS_ROUTE_MAX_ALT_FT:-}  # leer: keine Höhengrenze
      ANALYSIS_CORRIDOR_M: ${ANALYSIS_CORRIDOR_M:-1852}
      ANALYSIS_CORRIDOR_MIN_S: ${ANALYSIS_CORRIDOR_MIN_S:-30}
      ANALYSIS_APPROACH_TOL_M: ${ANALYSIS_APPROACH_TOL_M:-}  # leer: wie ANALYSIS_CORRIDOR_M
      ANALYSIS_REVIEW_MAX_GAP_S: ${ANALYSIS_REVIEW_MAX_GAP_S:-30}
      ANALYSIS_ZONES_FILE: /zones/geofences.geojson
      ANALYSIS_PROCEDURES_FILE: /zones/procedures.yaml
```

In `nas/.env.example` die beiden Zeilen

```bash
# Ordner mit geofences.geojson (Standard: config/local im Repo, gitignored)
ZONES_DIR=../config/local
```

ersetzen durch:

```bash
# Ordner mit geofences.geojson und procedures.yaml (Standard: config/local im Repo, gitignored)
ZONES_DIR=../config/local
# Flugroutenvergleich: Höhengrenze des Vergleichs in ft (leer = keine), siehe docs/routes.md
ANALYSIS_ROUTE_MAX_ALT_FT=
```

In `docs/analysis.md` im Abschnitt `## Parameter` nach der Tabellenzeile zu `ANALYSIS_MAX_LAG_S` einfügen:

```markdown
| `ANALYSIS_PROCEDURES_FILE` | – | Verfahrensdatei (im NAS-Stack `/zones/procedures.yaml`); fehlt sie, entfällt der Routenvergleich |
| `ANALYSIS_ROLE_NEAR_M` | 10000 | Umkreis um BER, in dem ein Abflug beginnt bzw. ein Anflug endet |
| `ANALYSIS_ROLE_MAX_ALT_FT` | 3000 | Höhe, unter der der Flug dort sein muss |
| `ANALYSIS_DIRECTION_DIST_M` | 15000 | Abstand, bis zu dem der Bezugskurs gemessen wird |
| `ANALYSIS_DIRECTION_TOL_DEG` | 30 | Größte Abweichung des Bezugskurses vom Startbahnkurs |
| `ANALYSIS_DIRECTION_MIN_FLIGHTS` | 3 | Mindestzahl Stimmen je 30-Minuten-Fenster |
| `ANALYSIS_DIRECTION_MIN_SHARE` | 0.8 | Mindestanteil der Mehrheit im Fenster |
| `ANALYSIS_ASSIGN_RATIO` | 2.0 | Faktor, um den das zweitbeste Verfahren weiter entfernt sein muss |
| `ANALYSIS_ROUTE_MAX_ALT_FT` | leer | Höhengrenze des bewerteten Abschnitts (leer = keine) |
| `ANALYSIS_CORRIDOR_M` | 1852 | Halbe Korridorbreite |
| `ANALYSIS_CORRIDOR_MIN_S` | 30 | Mindestdauer außerhalb des Korridors für eine Abweichung |
| `ANALYSIS_APPROACH_TOL_M` | = Korridor | Toleranz für eine auffällige Annäherung |
| `ANALYSIS_REVIEW_MAX_GAP_S` | 30 | Größte Positionslücke im bewerteten Abschnitt für einen Prüffall |
```

- [ ] **Step 5: Tests laufen lassen**

Run: `pytest tests/analysis -v && docker compose -f nas/docker-compose.yml --env-file nas/.env.example config -q`
Expected: alle PASS, Compose-Datei gültig.

- [ ] **Step 6: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/config.py nas/ docs/analysis.md tests/analysis/test_analysis_config.py tests/analysis/test_analysis_compose_env.py
git commit -m "analysis: Parameter für den Flugroutenvergleich"
```

---

### Task 3: Lokale Ebene `geo`

**Files:**
- Create: `analysis/src/analysis/geo.py`
- Test: `tests/analysis/test_geo.py`

**Interfaces:**
- Consumes: `segment.EARTH_RADIUS_M`, `segment.haversine_m` (M3)
- Produces:
  - `XY = tuple[float, float]` (x Ost, y Nord, m)
  - `Local(lat0: float, lon0: float)` mit `xy(lat, lon) -> XY` und `latlon(x, y) -> tuple[float, float]`
  - `azimuth_deg(a: XY, b: XY) -> float` (0 = Nord, 90 = Ost)
  - `angle_diff(a: float, b: float) -> float` (0–180)
  - `length(line: list[XY]) -> float`
  - `exit_point(line: list[XY], radius: float) -> XY | None` – erster Punkt entlang der Linie mit Abstand ≥ `radius` vom Ursprung, interpoliert
  - `Projection(along_m: float, dist_m: float, within: bool)`; `project(p: XY, line: list[XY]) -> Projection`
  - `distance_to_line(p: XY, line: list[XY]) -> float`

- [ ] **Step 1: Tests schreiben** – `tests/analysis/test_geo.py`:

```python
import math

import pytest

from analysis.geo import Local, angle_diff, azimuth_deg, exit_point, length, project
from analysis.segment import haversine_m

LOCAL = Local(50.0, 10.0)


def test_round_trip_and_true_distance_from_center():
    lat, lon = LOCAL.latlon(12000.0, -8000.0)
    x, y = LOCAL.xy(lat, lon)
    assert (x, y) == (pytest.approx(12000.0, abs=1e-6), pytest.approx(-8000.0, abs=1e-6))
    assert math.hypot(x, y) == pytest.approx(haversine_m(50.0, 10.0, lat, lon), rel=1e-9)
    assert LOCAL.xy(50.0, 10.0) == (0.0, 0.0)


def test_azimuth_and_angle_diff():
    assert azimuth_deg((0, 0), (0, 1)) == 0
    assert azimuth_deg((0, 0), (1, 0)) == 90
    assert azimuth_deg((0, 0), (0, -1)) == 180
    assert azimuth_deg((0, 0), (-1, 0)) == 270
    assert angle_diff(350, 10) == 20
    assert angle_diff(90, 270) == 180


def test_exit_point():
    assert exit_point([(0, 0), (0, 20000)], 15000) == (0, 15000)
    assert exit_point([(0, 0), (0, 5000)], 15000) is None
    assert exit_point([(0, 20000), (0, 30000)], 15000) == (0, 20000)
    x, y = exit_point([(0, 0), (30000, 30000)], 15000)
    assert (x, y) == (pytest.approx(15000 / math.sqrt(2)), pytest.approx(15000 / math.sqrt(2)))


def test_project_inside_and_beyond_line():
    line = [(0.0, 0.0), (10000.0, 0.0)]
    p = project((5000, 300), line)
    assert (p.along_m, p.dist_m, p.within) == (5000, 300, True)
    before = project((-200, 100), line)
    assert (before.dist_m, before.within) == (pytest.approx(223.607, abs=1e-3), False)
    assert project((10500, 0), line).within is False


def test_project_at_inner_vertex_counts_as_within():
    line = [(0.0, 0.0), (10000.0, 0.0), (10000.0, 10000.0)]
    p = project((10500, -500), line)
    assert (p.along_m, p.dist_m, p.within) == (10000, pytest.approx(707.107, abs=1e-3), True)


def test_length():
    assert length([(0, 0), (3000, 4000), (3000, 0)]) == 9000
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_geo.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis.geo'`.

- [ ] **Step 3: Implementierung** – `analysis/src/analysis/geo.py`:

```python
"""Lokale Ebene um den Flughafen-Referenzpunkt und Linienrechnung (ohne Datenbank).

Mittabstandstreue Azimutalprojektion auf der Kugel: Abstände und Richtungen vom Mittelpunkt
sind exakt, übrige Abstände im Umkreis von 100 km auf wenige Meter genau – vernachlässigbar
gegenüber der Korridorbreite. Koordinaten in der Ebene: x nach Osten, y nach Norden, in m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from analysis.segment import EARTH_RADIUS_M

XY = tuple[float, float]


class Local:
    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0, self.lon0 = lat0, lon0
        self._sin0 = math.sin(math.radians(lat0))
        self._cos0 = math.cos(math.radians(lat0))

    def xy(self, lat: float, lon: float) -> XY:
        phi, dl = math.radians(lat), math.radians(lon - self.lon0)
        cos_c = self._sin0 * math.sin(phi) + self._cos0 * math.cos(phi) * math.cos(dl)
        c = math.acos(max(-1.0, min(1.0, cos_c)))
        k = 1.0 if c < 1e-12 else c / math.sin(c)
        x = k * math.cos(phi) * math.sin(dl)
        y = k * (self._cos0 * math.sin(phi) - self._sin0 * math.cos(phi) * math.cos(dl))
        return x * EARTH_RADIUS_M, y * EARTH_RADIUS_M

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        rho = math.hypot(x, y)
        if rho < 1e-9:
            return self.lat0, self.lon0
        c = rho / EARTH_RADIUS_M
        lat = math.asin(math.cos(c) * self._sin0 + y * math.sin(c) * self._cos0 / rho)
        lon = math.radians(self.lon0) + math.atan2(
            x * math.sin(c), rho * self._cos0 * math.cos(c) - y * self._sin0 * math.sin(c)
        )
        return math.degrees(lat), (math.degrees(lon) + 540) % 360 - 180


def azimuth_deg(a: XY, b: XY) -> float:
    """Kurs von ``a`` nach ``b`` in Grad (0 = Nord, 90 = Ost)."""
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def angle_diff(a: float, b: float) -> float:
    """Kleinster Winkel zwischen zwei Kursen in Grad (0–180)."""
    return abs((a - b + 180) % 360 - 180)


def length(line: list[XY]) -> float:
    return sum(math.dist(a, b) for a, b in zip(line, line[1:], strict=False))


def exit_point(line: list[XY], radius: float) -> XY | None:
    """Erster Punkt entlang ``line``, an dem der Abstand zum Ursprung ``radius`` erreicht
    (zwischen zwei Stützpunkten linear interpoliert); ``None``, wenn das nie geschieht."""
    for a, b in zip(line, line[1:], strict=False):
        da, db = math.hypot(*a), math.hypot(*b)
        if da >= radius:
            return a
        if db >= radius:
            # Schnitt der Strecke a→b mit dem Kreis: |a + t(b−a)| = radius
            dx, dy = b[0] - a[0], b[1] - a[1]
            qa = dx * dx + dy * dy
            qb = 2 * (a[0] * dx + a[1] * dy)
            qc = da * da - radius * radius
            t = (-qb + math.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa)
            return a[0] + t * dx, a[1] + t * dy
    if line and math.hypot(*line[-1]) >= radius:
        return line[-1]
    return None


@dataclass(frozen=True)
class Projection:
    along_m: float  # Strecke entlang der Linie bis zum Lotfußpunkt
    dist_m: float  # seitlicher Abstand
    within: bool  # Lotfußpunkt zwischen Anfang und Ende der Linie


def project(p: XY, line: list[XY]) -> Projection:
    """Nächster Punkt der Linie zu ``p``. ``within`` ist falsch, wenn der nächste Punkt nur
    durch Abschneiden vor dem Anfang oder hinter dem Ende entsteht."""
    best: tuple[float, float, bool] | None = None
    start = 0.0
    last = len(line) - 2
    for i, (a, b) in enumerate(zip(line, line[1:], strict=False)):
        dx, dy = b[0] - a[0], b[1] - a[1]
        seg = math.hypot(dx, dy)
        t_raw = 0.0 if seg == 0 else ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (seg * seg)
        t = min(1.0, max(0.0, t_raw))
        d = math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
        within = not ((i == 0 and t_raw < 0) or (i == last and t_raw > 1))
        if best is None or d < best[1]:
            best = (start + t * seg, d, within)
        start += seg
    along, dist, within = best
    return Projection(along, dist, within)


def distance_to_line(p: XY, line: list[XY]) -> float:
    if len(line) == 1:
        return math.dist(p, line[0])
    return project(p, line).dist_m
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/analysis/test_geo.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/geo.py tests/analysis/test_geo.py
git commit -m "analysis: lokale Ebene um den Flughafen-Referenzpunkt"
```

---

### Task 4: Verfahrensdatei lesen und prüfen, Beispiel- und Testflughafen

**Files:**
- Create: `analysis/src/analysis/procedures.py` (ohne Datenbankteil, der folgt in Task 5)
- Create: `config/procedures.example.yaml`, `tests/fixtures/procedures.test.yaml`, `tests/fixtures/synthetic/routes.py`
- Modify: `requirements-dev.txt`, `analysis/Dockerfile`
- Test: `tests/analysis/test_procedures.py`

**Interfaces:**
- Consumes: `geo.Local`, `geo.azimuth_deg`, `geo.exit_point`, `geo.length`, `geo.XY` (Task 3); `events.sector` (M3); `segment.haversine_m`, `segment.Point` (M3)
- Produces:
  - `ProcedureError(ValueError)`
  - `Procedure(name, kind, runway, runway_heading_deg: float, direction, sector, airac: str | None, valid_from: date, valid_to: date | None, source: str | None, waypoints: tuple[str, ...], line: tuple[tuple[float, float], ...], constraints: dict, length_m: float)` mit `content_hash() -> str`; `line` als (lat, lon), bei SID ab der Gegenschwelle
  - `direction_class(heading_deg: float) -> str` (`west` 180–359°, sonst `east`)
  - `opposite_runway(runway: str) -> str`
  - `parse_coord(value, what: str) -> tuple[float, float]` (lat, lon)
  - `parse_procedures(data, *, ber_lat, ber_lon, ber_radius_m) -> list[Procedure]`
  - `read_procedures(path: Path, *, ber_lat, ber_lon, ber_radius_m) -> list[Procedure]`
  - Fixture `synthetic.routes`: `CENTER`, `LOCAL`, `PROCEDURES_FILE`, Wegpunkte `THR_27`, `THR_09`, `TWEST`, `TEAST`, `WNMID`, `WNORD`, `WSMID`, `WSUED`, `ONMID`, `ONORD`, `OSMID`, `OSUED` (XY), `fly(waypoints, start, *, speed_kt=250, alt_ft=500, vrate_fpm=2000, step_s=1.0, icao24="ff0101", callsign="TST101") -> list[dict]` (Zeilen für `insert_positions`), `points(rows) -> list[Point]`

Format und Prüfregeln stehen in Spezifikation Abschnitt 3. Festlegungen: Startbahnbezeichnung `01`–`36` mit optional `L`/`C`/`R` in Anführungszeichen; die Gegenschwelle (z. B. `07L` zu `25R`) muss ebenfalls eingetragen sein; eine STAR braucht mindestens zwei Wegpunkte (eine Linie), eine SID mindestens einen; doppelte Schlüssel in der YAML-Datei werden abgelehnt (PyYAML übernähme sonst stillschweigend den letzten); YAML-Syntaxfehler nennen nur die Zeile, weil PyYAML sonst den Inhalt zitiert.

- [ ] **Step 1: Abhängigkeit** – in `requirements-dev.txt` die Zeile `PyYAML==6.0.2` anhängen; in `analysis/Dockerfile` die `RUN`-Zeile ersetzen durch:

```dockerfile
RUN pip install --no-cache-dir "psycopg[binary]==3.2.3" "PyYAML==6.0.2" \
```

Dann: `pip install -r requirements-dev.txt`.

- [ ] **Step 2: Beispiel- und Testdateien**

`config/procedures.example.yaml` (alle Werte erfunden, Atlantik; Referenzpunkt 45,0° N / 30,0° W):

```yaml
# Vorlage für config/local/procedures.yaml (gitignored). Alle Werte sind erfunden und liegen im
# Atlantik; echte Verfahren aus der DFS-AIP nur in config/local/ eintragen (Urheberrecht DFS).
# Prüfen: python scripts/check_procedures.py <datei> --ber-lat 45.0 --ber-lon -30.0
source: "erfunden, Beispiel"   # frei, erscheint in procedures.source
waypoints:
  ABCDE: "45 30 00.00N 030 30 00.00W"   # Grad Minuten Sekunden wie in der AIP
  KLMNO: "45 00 00.00N 030 15 00.00W"
  FGHIJ: [45.4, -29.9]                   # alternativ Dezimalgrad lat, lon
  PQRST: [45.0, -29.75]
runways:
  "25": "45 00 16.18N 029 58 55.89W"   # Schwelle, von der aus abgeflogen bzw. auf die angeflogen wird
  "07": "44 59 43.81N 030 01 04.10W"
procedures:
  - name: ABCDE1W
    kind: SID                # SID oder STAR
    runway: "25"
    valid_from: 2026-11-05   # AIRAC-Beginn
    valid_to: null           # offen
    airac: "2611"
    route: [KLMNO, ABCDE]    # bei SID beginnt die Linie an der Schwelle der Gegenrichtung
    constraints:             # optional, nur zur Anzeige
      ABCDE: {alt_ft_min: 5000, speed_kt_max: 250}
  - name: FGHIJ1W
    kind: STAR
    runway: "25"
    valid_from: 2026-11-05
    valid_to: null
    airac: "2611"
    route: [FGHIJ, PQRST]    # STAR ohne Endanflug
  - name: FGHIJ1E
    kind: SID
    runway: "07"
    valid_from: 2026-11-05
    valid_to: null
    airac: "2611"
    route: [PQRST, FGHIJ]
  - name: ABCDE1E
    kind: STAR
    runway: "07"
    valid_from: 2026-11-05
    valid_to: null
    airac: "2611"
    route: [ABCDE, KLMNO]
```

`tests/fixtures/procedures.test.yaml` (Koordinaten = Wegpunkte des Testflughafens, siehe Dateiübersicht; `TWEST` in Grad/Minuten/Sekunden):

```yaml
# Erfundener Flughafen um 50° N / 10° O für Tests (keine realen Verfahren).
# Startbahn 27/09 in Ost-West-Richtung, je zwei SIDs und STARs je Betriebsrichtung.
source: "synthetisch, Tests"
waypoints:
  TWEST: "49 59 59.22N 009 46 34.12E"
  TEAST: [49.999785, 10.223854]
  WNMID: [50.179526, 9.719131]
  WNORD: [50.358688, 9.506626]
  WSMID: [49.819801, 9.721225]
  WSUED: [49.639251, 9.513954]
  ONMID: [50.179526, 10.280869]
  ONORD: [50.358688, 10.493374]
  OSMID: [49.819801, 10.278775]
  OSUED: [49.639251, 10.486046]
runways:
  "27": [49.999998, 10.020986]
  "09": [49.999998, 9.979014]
procedures:
  # Betriebsrichtung West: Abflug nach Westen, Anflug von Osten
  - {name: WNORD1W, kind: SID, runway: "27", valid_from: 2026-11-05, valid_to: null,
     airac: "2611", route: [TWEST, WNMID, WNORD], constraints: {TWEST: {alt_ft_min: 3000}}}
  - {name: WSUED1W, kind: SID, runway: "27", valid_from: 2026-11-05, valid_to: null,
     airac: "2611", route: [TWEST, WSMID, WSUED]}
  - {name: ONORD1W, kind: STAR, runway: "27", valid_from: 2026-11-05, valid_to: null,
     airac: "2611", route: [ONORD, ONMID, TEAST]}
  - {name: OSUED1W, kind: STAR, runway: "27", valid_from: 2026-11-05, valid_to: null,
     airac: "2611", route: [OSUED, OSMID, TEAST]}
  # Betriebsrichtung Ost: Abflug nach Osten, Anflug von Westen
  - {name: ONORD1E, kind: SID, runway: "09", valid_from: 2026-11-05, valid_to: null,
     airac: "2611", route: [TEAST, ONMID, ONORD]}
  - {name: OSUED1E, kind: SID, runway: "09", valid_from: 2026-11-05, valid_to: null,
     airac: "2611", route: [TEAST, OSMID, OSUED]}
  - {name: WNORD1E, kind: STAR, runway: "09", valid_from: 2026-11-05, valid_to: null,
     airac: "2611", route: [WNORD, WNMID, TWEST]}
  - {name: WSUED1E, kind: STAR, runway: "09", valid_from: 2026-11-05, valid_to: null,
     airac: "2611", route: [WSUED, WSMID, TWEST]}
```

`tests/fixtures/synthetic/routes.py`:

```python
"""Synthetische An- und Abflüge am erfundenen Flughafen um 50° N / 10° O.

Wegpunkte in der lokalen Ebene (x Ost, y Nord, m) um den Referenzpunkt; dieselbe Projektion
wie in ``analysis.geo``, damit Abstände in Tests exakt sind. ICAO24 beginnt mit ``ff``.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from analysis.geo import XY, Local
from analysis.segment import Point

CENTER = (50.0, 10.0)
LOCAL = Local(*CENTER)
PROCEDURES_FILE = Path(__file__).resolve().parents[1] / "procedures.test.yaml"
KT_TO_MS = 1852 / 3600

# Wegpunkte aus procedures.test.yaml in der lokalen Ebene
THR_27, THR_09 = (1500.0, 0.0), (-1500.0, 0.0)
TWEST, TEAST = (-16000.0, 0.0), (16000.0, 0.0)
WNMID, WNORD = (-20000.0, 20000.0), (-35000.0, 40000.0)
WSMID, WSUED = (-20000.0, -20000.0), (-35000.0, -40000.0)
ONMID, ONORD = (20000.0, 20000.0), (35000.0, 40000.0)
OSMID, OSUED = (20000.0, -20000.0), (35000.0, -40000.0)


def fly(
    waypoints: list[XY],
    start: datetime,
    *,
    speed_kt: float = 250,
    alt_ft: float = 500,
    vrate_fpm: float = 2000,
    step_s: float = 1.0,
    icao24: str = "ff0101",
    callsign: str | None = "TST101",
) -> list[dict]:
    """Positionen entlang der Wegpunktfolge mit fester Geschwindigkeit und Steigrate, im
    Format von ``synthetic.tracks.insert_positions``."""
    speed = speed_kt * KT_TO_MS
    legs = list(zip(waypoints, waypoints[1:], strict=False))
    total = sum(math.dist(a, b) for a, b in legs)
    rows = []
    i = 0
    while speed * step_s * i <= total:
        s = speed * step_s * i
        for a, b in legs:
            d = math.dist(a, b)
            if s <= d:
                f = s / d
                x, y = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
                break
            s -= d
        lat, lon = LOCAL.latlon(x, y)
        rows.append(
            {
                "ts": start + timedelta(seconds=step_s * i),
                "icao24": icao24,
                "callsign": callsign,
                "lat": lat,
                "lon": lon,
                "alt_baro_ft": round(alt_ft + vrate_fpm * step_s * i / 60),
                "baro_rate_fpm": round(vrate_fpm),
                "on_ground": False,
            }
        )
        i += 1
    return rows


def points(rows: list[dict]) -> list[Point]:
    return [
        Point(
            r["ts"],
            r["lat"],
            r["lon"],
            r["alt_baro_ft"],
            r["baro_rate_fpm"],
            r["callsign"],
            r["on_ground"],
        )
        for r in rows
    ]
```

- [ ] **Step 3: Tests schreiben** – `tests/analysis/test_procedures.py`. Erwartete Werte (in der lokalen Ebene um 45,0° N / 30,0° W nachgerechnet): `WESTA` liegt 39313 m westlich, die SID-Linie 09 → WESTA → NORDA ist 82904 m lang und verlässt den 40-km-Radius kurz hinter WESTA (Sektor `W`); die STAR OSTAB → OSTAA betritt ihn von Osten (`O`). Mit Radius 100 km liegen beide Linien ganz innerhalb: SID → letzter Wegpunkt NORDA (313,6°, `NW`), STAR → erster Wegpunkt OSTAB (70,2°, `O`). `[47.0, -30.0]` liegt 222 km nördlich.

```python
import copy
from datetime import date
from pathlib import Path

import pytest

from analysis.procedures import (
    ProcedureError,
    direction_class,
    opposite_runway,
    parse_coord,
    parse_procedures,
    read_procedures,
)

ROOT = Path(__file__).resolve().parents[2]
BER = {"ber_lat": 45.0, "ber_lon": -30.0, "ber_radius_m": 40000.0}
DATA = {
    "source": "erfunden",
    "waypoints": {
        "WESTA": "45 00 00.00N 030 30 00.00W",
        "NORDA": [45.4, -30.6],
        "OSTAA": [45.0, -29.5],
        "OSTAB": [45.2, -29.2],
    },
    "runways": {"27": [45.0, -29.98], "09": [45.0, -30.02]},
    "procedures": [
        {
            "name": "WESTA1W",
            "kind": "SID",
            "runway": "27",
            "valid_from": date(2026, 11, 5),
            "valid_to": None,
            "airac": "2611",
            "route": ["WESTA", "NORDA"],
            "constraints": {"WESTA": {"alt_ft_min": 5000}},
        },
        {
            "name": "OSTAB1W",
            "kind": "STAR",
            "runway": "27",
            "valid_from": "2026-11-05",
            "route": ["OSTAB", "OSTAA"],
        },
    ],
}


def data(**changes):
    d = copy.deepcopy(DATA)
    for path, value in changes.items():
        *keys, last = path.split("__")
        target = d
        for k in keys:
            target = target[int(k)] if isinstance(target, list) else target[k]
        target[int(last) if isinstance(target, list) else last] = value
    return d


def test_coordinates_dms_and_decimal():
    assert parse_coord("45 30 15.50N 030 05 00.00W", "x") == pytest.approx((45.504306, -30.083333))
    assert parse_coord("453015.50N0300500.00W", "x") == pytest.approx((45.504306, -30.083333))
    assert parse_coord([45.4, -30.6], "x") == (45.4, -30.6)


def test_geometry_direction_and_sector():
    sid, star = parse_procedures(DATA, **BER)
    assert sid.line[0] == (45.0, -30.02)  # SID beginnt an der Gegenschwelle 09
    assert sid.line[1] == pytest.approx((45.0, -30.5))
    assert (sid.runway_heading_deg, sid.direction, sid.sector) == (270.0, "west", "W")
    assert (sid.waypoints, sid.airac, sid.source) == (("WESTA", "NORDA"), "2611", "erfunden")
    assert sid.constraints == {"WESTA": {"alt_ft_min": 5000}}
    assert sid.length_m == 82904
    assert star.line[0] == (45.2, -29.2)  # STAR ohne Endanflug
    assert (star.direction, star.sector, star.valid_from, star.valid_to) == (
        "west",
        "O",
        date(2026, 11, 5),
        None,
    )


def test_east_runway():
    (sid, _) = parse_procedures(data(procedures__0__runway="09"), **BER)
    assert (sid.runway_heading_deg, sid.direction) == (90.0, "east")
    assert sid.line[0] == (45.0, -29.98)


def test_sector_of_line_entirely_inside_radius():
    sid, star = parse_procedures(DATA, **(BER | {"ber_radius_m": 100000.0}))
    assert (sid.sector, star.sector) == ("NW", "O")  # letzter bzw. erster Wegpunkt


def test_opposite_runway_and_direction_class():
    assert [opposite_runway(r) for r in ("25R", "07L", "36", "18", "09C", "01")] == [
        "07L",
        "25R",
        "18",
        "36",
        "27C",
        "19",
    ]
    assert [direction_class(h) for h in (0, 179.9, 180, 359.9)] == ["east", "east", "west", "west"]


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"procedures__0__route": ["WESTA", "XXXXX"]}, "Wegpunkt 'XXXXX' unbekannt"),
        ({"procedures__0__runway": "25L"}, "Startbahn '25L' unbekannt"),
        ({"runways": {"27": [45.0, -29.98]}}, "Gegenschwelle 09 unbekannt"),
        ({"waypoints__WESTA": "45 00 N"}, "WESTA, Feld Koordinate: Koordinate unlesbar"),
        ({"waypoints__NORDA": [95.0, -30.0]}, "außerhalb ±90/±180"),
        ({"waypoints__NORDA": [47.0, -30.0]}, "weiter als 200 km"),
        ({"runways__27": "45 00 00.00N 029 58 61.00W"}, "Startbahn 27, Feld Schwelle"),
        ({"procedures__0__route": []}, "mindestens einen Wegpunkt"),
        ({"procedures__1__route": ["OSTAA"]}, "mindestens zwei Wegpunkte"),
        ({"procedures__0__valid_to": date(2026, 11, 1)}, "valid_to: liegt vor valid_from"),
        ({"procedures__0__valid_from": "05.11.2026"}, "valid_from: Datum JJJJ-MM-TT"),
        ({"procedures__0__kind": "APP"}, "SID oder STAR"),
        ({"procedures__1__name": "WESTA1W"}, "WESTA1W, Feld name: doppelt"),
        ({"procedures": []}, "Feld procedures: fehlt oder leer"),
    ],
)
def test_rejected(changes, message):
    with pytest.raises(ProcedureError, match=message):
        parse_procedures(data(**changes), **BER)


def test_same_name_without_overlap_is_allowed():
    d = data(procedures__1__name="WESTA1W", procedures__1__kind="SID")
    d["procedures"][0]["valid_to"] = date(2026, 12, 3)
    d["procedures"][1]["valid_from"] = date(2026, 12, 3)
    old, new = parse_procedures(d, **BER)
    assert (old.name, new.name) == ("WESTA1W", "WESTA1W")


def test_messages_contain_no_coordinates():
    with pytest.raises(ProcedureError) as e:
        parse_procedures(data(waypoints__NORDA=[47.0, -30.0]), **BER)
    assert "47" not in str(e.value) and "30" not in str(e.value)


def test_content_hash_reflects_content():
    a = parse_procedures(DATA, **BER)[0]
    b = parse_procedures(data(), **BER)[0]
    c = parse_procedures(data(procedures__0__airac="2612"), **BER)[0]
    assert a.content_hash() == b.content_hash() != c.content_hash()


def test_yaml_duplicate_key_and_syntax(tmp_path):
    dup = tmp_path / "dup.yaml"
    dup.write_text("waypoints:\n  WESTA: [45.0, -30.5]\n  WESTA: [45.1, -30.5]\n", "utf-8")
    with pytest.raises(ProcedureError, match="Zeile 3: Name 'WESTA' doppelt"):
        read_procedures(dup, **BER)
    bad = tmp_path / "bad.yaml"
    bad.write_text("waypoints:\n  WESTA: [45.0, -30.5\n", "utf-8")
    with pytest.raises(ProcedureError, match=r"bad.yaml: kein gültiges YAML \(Zeile \d+\)") as e:
        read_procedures(bad, **BER)
    assert "45.0" not in str(e.value)
    with pytest.raises(ProcedureError, match="nicht lesbar"):
        read_procedures(tmp_path / "fehlt.yaml", **BER)


def test_example_files_are_valid():
    example = read_procedures(ROOT / "config" / "procedures.example.yaml", **BER)
    assert {p.kind for p in example} == {"SID", "STAR"}
    fixture = read_procedures(
        ROOT / "tests" / "fixtures" / "procedures.test.yaml",
        ber_lat=50.0,
        ber_lon=10.0,
        ber_radius_m=40000.0,
    )
    assert [(p.name, p.direction, p.sector) for p in fixture] == [
        ("WNORD1W", "west", "NW"),
        ("WSUED1W", "west", "SW"),
        ("ONORD1W", "west", "NO"),
        ("OSUED1W", "west", "SO"),
        ("ONORD1E", "east", "NO"),
        ("OSUED1E", "east", "SO"),
        ("WNORD1E", "east", "NW"),
        ("WSUED1E", "east", "SW"),
    ]
```

- [ ] **Step 4: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_procedures.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis.procedures'`.

- [ ] **Step 5: Implementierung** – `analysis/src/analysis/procedures.py`:

```python
"""Flugverfahren (SID/STAR): YAML lesen und prüfen, Geometrie, Abgleich mit ``procedures``.

Die Datei wird als Ganzes geprüft; bei einem Fehler wird nichts geladen und die bisherige
Fassung bleibt aktiv. Fehlermeldungen nennen Eintrag und Feld, nie Koordinaten.
Geänderte Verfahren (gleicher Name, gleicher Gültigkeitsbeginn) erhalten eine neue Fassung;
die alte wird mit ``superseded_at`` geschlossen.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from analysis.events import sector
from analysis.geo import XY, Local, azimuth_deg, exit_point, length
from analysis.segment import haversine_m

KINDS = ("SID", "STAR")
MAX_WAYPOINT_DIST_M = 200_000
_RUNWAY = re.compile(r"^(0[1-9]|[12]\d|3[0-6])([LCR]?)$")
_DMS = re.compile(
    r"^\s*(\d{2})\s*(\d{2})\s*(\d{2}(?:\.\d+)?)\s*([NS])"
    r"\s*(\d{3})\s*(\d{2})\s*(\d{2}(?:\.\d+)?)\s*([EW])\s*$"
)


class ProcedureError(ValueError):
    pass


@dataclass(frozen=True)
class Procedure:
    name: str
    kind: str  # SID | STAR
    runway: str
    runway_heading_deg: float  # Kurs Schwelle → Gegenschwelle
    direction: str  # west | east
    sector: str
    airac: str | None
    valid_from: date
    valid_to: date | None
    source: str | None
    waypoints: tuple[str, ...]
    line: tuple[tuple[float, float], ...]  # (lat, lon); SID ab der Gegenschwelle
    constraints: dict = field(default_factory=dict)
    length_m: float = 0.0

    def content_hash(self) -> str:
        data = json.dumps(asdict(self), sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(data.encode()).hexdigest()


class _Loader(yaml.SafeLoader):
    """SafeLoader, der doppelte Schlüssel ablehnt statt den letzten zu übernehmen."""


def _mapping(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ProcedureError(f"Zeile {key_node.start_mark.line + 1}: Name {key!r} doppelt")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def direction_class(heading_deg: float) -> str:
    """Betriebsrichtung zu einem Kurs: 180–359° ``west``, 0–179° ``east``."""
    return "west" if 180 <= heading_deg % 360 < 360 else "east"


def opposite_runway(runway: str) -> str:
    m = _RUNWAY.match(runway)
    number = (int(m.group(1)) + 17) % 36 + 1
    return f"{number:02d}" + {"L": "R", "R": "L", "C": "C", "": ""}[m.group(2)]


def parse_coord(value, what: str) -> tuple[float, float]:
    """``"GG MM SS.ssN GGG MM SS.ssE"`` oder ``[lat, lon]`` → (lat, lon)."""
    if isinstance(value, str):
        m = _DMS.match(value)
        if not m:
            raise ProcedureError(f"{what}: Koordinate unlesbar")
        d1, m1, s1, ns, d2, m2, s2, ew = m.groups()
        if int(m1) >= 60 or float(s1) >= 60 or int(m2) >= 60 or float(s2) >= 60:
            raise ProcedureError(f"{what}: Koordinate unlesbar")
        lat = (int(d1) + int(m1) / 60 + float(s1) / 3600) * (1 if ns == "N" else -1)
        lon = (int(d2) + int(m2) / 60 + float(s2) / 3600) * (1 if ew == "E" else -1)
    elif (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        lat, lon = float(value[0]), float(value[1])
    else:
        raise ProcedureError(f"{what}: Koordinate unlesbar")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ProcedureError(f"{what}: Koordinate außerhalb ±90/±180")
    return lat, lon


def _date(value, what: str, required: bool) -> date | None:
    if value is None and not required:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ProcedureError(f"{what}: Datum JJJJ-MM-TT erwartet")


def _overlap(a: Procedure, b: Procedure) -> bool:
    return a.valid_from < (b.valid_to or date.max) and b.valid_from < (a.valid_to or date.max)


def _sector(line: list[XY], kind: str, radius: float) -> str:
    """Richtung vom Referenzpunkt zum Punkt, an dem die Linie den Radius verlässt (SID) bzw.
    betritt (STAR); liegt sie ganz innerhalb, der letzte bzw. erste Punkt."""
    outward = line if kind == "SID" else line[::-1]
    point = exit_point(outward, radius) or outward[-1]
    return sector(azimuth_deg((0.0, 0.0), point))


def parse_procedures(
    data, *, ber_lat: float, ber_lon: float, ber_radius_m: float
) -> list[Procedure]:
    if not isinstance(data, dict):
        raise ProcedureError("Datei: Objekt mit waypoints, runways und procedures erwartet")
    source = data.get("source")
    source = None if source is None else str(source)
    for key, kind in (("waypoints", dict), ("runways", dict), ("procedures", list)):
        if not isinstance(data.get(key), kind) or not data[key]:
            raise ProcedureError(f"Datei, Feld {key}: fehlt oder leer")

    waypoints: dict[str, tuple[float, float]] = {}
    for name, value in data["waypoints"].items():
        if not isinstance(name, str) or not name.strip():
            raise ProcedureError(f"Wegpunkt {name!r}: Name muss Text sein")
        lat, lon = parse_coord(value, f"Wegpunkt {name}, Feld Koordinate")
        if haversine_m(lat, lon, ber_lat, ber_lon) > MAX_WAYPOINT_DIST_M:
            raise ProcedureError(
                f"Wegpunkt {name}, Feld Koordinate: weiter als 200 km vom Referenzpunkt"
            )
        waypoints[name] = (lat, lon)

    runways: dict[str, tuple[float, float]] = {}
    for name, value in data["runways"].items():
        if not isinstance(name, str) or not _RUNWAY.match(name):
            raise ProcedureError(f'Startbahn {name!r}: Bezeichnung wie "25R" erwartet')
        runways[name] = parse_coord(value, f"Startbahn {name}, Feld Schwelle")

    local = Local(ber_lat, ber_lon)
    procedures: list[Procedure] = []
    for i, p in enumerate(data["procedures"]):
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"]:
            raise ProcedureError(f"Verfahren Nr. {i + 1}, Feld name: fehlt")
        name = p["name"]
        what = f"Verfahren {name}"
        kind = p.get("kind")
        if kind not in KINDS:
            raise ProcedureError(f"{what}, Feld kind: SID oder STAR erwartet")
        runway = p.get("runway")
        if not isinstance(runway, str) or runway not in runways:
            raise ProcedureError(f"{what}, Feld runway: Startbahn {runway!r} unbekannt")
        opposite = opposite_runway(runway)
        if opposite not in runways:
            raise ProcedureError(f"{what}, Feld runway: Gegenschwelle {opposite} unbekannt")
        valid_from = _date(p.get("valid_from"), f"{what}, Feld valid_from", required=True)
        valid_to = _date(p.get("valid_to"), f"{what}, Feld valid_to", required=False)
        if valid_to is not None and valid_to < valid_from:
            raise ProcedureError(f"{what}, Feld valid_to: liegt vor valid_from")
        route = p.get("route")
        if not isinstance(route, list) or len(route) < (1 if kind == "SID" else 2):
            minimum = "einen Wegpunkt" if kind == "SID" else "zwei Wegpunkte"
            raise ProcedureError(f"{what}, Feld route: mindestens {minimum} erwartet")
        for wp in route:
            if not isinstance(wp, str) or wp not in waypoints:
                raise ProcedureError(f"{what}, Feld route: Wegpunkt {wp!r} unbekannt")
        constraints = p.get("constraints") or {}
        if not isinstance(constraints, dict):
            raise ProcedureError(f"{what}, Feld constraints: Zuordnung je Wegpunkt erwartet")
        airac = p.get("airac")

        line = [waypoints[wp] for wp in route]
        if kind == "SID":
            line.insert(0, runways[opposite])
        line_xy = [local.xy(*c) for c in line]
        heading = azimuth_deg(local.xy(*runways[runway]), local.xy(*runways[opposite]))
        proc = Procedure(
            name=name,
            kind=kind,
            runway=runway,
            runway_heading_deg=round(heading, 1),
            direction=direction_class(heading),
            sector=_sector(line_xy, kind, ber_radius_m),
            airac=None if airac is None else str(airac),
            valid_from=valid_from,
            valid_to=valid_to,
            source=source,
            waypoints=tuple(route),
            line=tuple(line),
            constraints=constraints,
            length_m=round(length(line_xy)),
        )
        for other in procedures:
            if other.name == name and _overlap(other, proc):
                raise ProcedureError(f"{what}, Feld name: doppelt bei überlappender Gültigkeit")
        procedures.append(proc)
    return procedures


def read_procedures(
    path: Path, *, ber_lat: float, ber_lon: float, ber_radius_m: float
) -> list[Procedure]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ProcedureError(f"{path.name}: nicht lesbar ({e.strerror})") from e
    try:
        data = yaml.load(text, Loader=_Loader)
    except yaml.MarkedYAMLError as e:
        # Nur die Zeile nennen: die Meldung von PyYAML zitiert sonst den Inhalt.
        line = e.problem_mark.line + 1 if e.problem_mark else "?"
        raise ProcedureError(f"{path.name}: kein gültiges YAML (Zeile {line})") from None
    except yaml.YAMLError:
        raise ProcedureError(f"{path.name}: kein gültiges YAML") from None
    return parse_procedures(data, ber_lat=ber_lat, ber_lon=ber_lon, ber_radius_m=ber_radius_m)
```

- [ ] **Step 6: Tests laufen lassen**

Run: `pytest tests/analysis -v && docker build -f analysis/Dockerfile -t flightdb-analysis:test .`
Expected: alle PASS (`test_procedures.py`: 24), Image baut.

- [ ] **Step 7: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/procedures.py analysis/Dockerfile requirements-dev.txt config/procedures.example.yaml tests/fixtures/procedures.test.yaml tests/fixtures/synthetic/routes.py tests/analysis/test_procedures.py
git commit -m "analysis: Verfahrensdatei lesen, prüfen und Geometrie ableiten"
```

---

### Task 5: Verfahren in der Datenbank versionieren

**Files:**
- Modify: `analysis/src/analysis/procedures.py`
- Test: `tests/db/test_analysis_procedures.py`

**Interfaces:**
- Consumes: `Procedure`, `read_procedures` (Task 4), Tabelle `procedures` (Task 1), `synthetic.routes.PROCEDURES_FILE` (Task 4)
- Produces:
  - `ProcedureSync(changed: list[str], removed: list[str])`
  - `load_procedures(conn: psycopg.Connection, procedures: list[Procedure]) -> ProcedureSync`

Versionierung wie bei `geofences`: Schlüssel ist (`name`, `valid_from`). Gleicher Inhalt (`content_hash`) → keine Änderung; anderer Inhalt → alte Zeile `superseded_at = now()`, neue Zeile. Verfahren, die in der Datei fehlen, werden ebenfalls mit `superseded_at` geschlossen (wie entfernte Zonen); sonst ließe sich ein fehlerhaft eingetragenes Verfahren nicht mehr entfernen. Alles in einer Transaktion.

- [ ] **Step 1: Tests schreiben** – `tests/db/test_analysis_procedures.py` (die Länge in PostGIS ist ellipsoidisch, in Python sphärisch: 0,15 % Unterschied):

```python
import psycopg
import pytest
from synthetic.routes import PROCEDURES_FILE

from analysis.procedures import load_procedures, read_procedures

pytestmark = pytest.mark.db

BER = {"ber_lat": 50.0, "ber_lon": 10.0, "ber_radius_m": 40000.0}


def procedures(text=None, tmp_path=None):
    if text is None:
        return read_procedures(PROCEDURES_FILE, **BER)
    path = tmp_path / "procedures.yaml"
    path.write_text(text, encoding="utf-8")
    return read_procedures(path, **BER)


def rows(dsn):
    with psycopg.connect(dsn) as c:
        return c.execute(
            "SELECT name, airac, superseded_at IS NULL FROM procedures ORDER BY id"
        ).fetchall()


def test_load_stores_geometry_and_attributes(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        result = load_procedures(c, procedures())
        assert len(result.changed) == 8 and result.removed == []
        row = c.execute(
            "SELECT kind, runway, runway_heading_deg, direction, sector, ST_NPoints(geom),"
            " ST_SRID(geom), waypoints, constraints, round(ST_Length(geom::geography))"
            " FROM procedures WHERE name = 'WNORD1W'"
        ).fetchone()
    assert row == (
        "SID",
        "27",
        270.0,
        "west",
        "NW",
        4,
        4326,
        ["TWEST", "WNMID", "WNORD"],
        {"TWEST": {"alt_ft_min": 3000}},
        pytest.approx(59896, rel=0.005),  # Kugel in Python, Ellipsoid in PostGIS
    )


def test_unchanged_reload_keeps_version(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_procedures(c, procedures())
        result = load_procedures(c, procedures())
    assert (result.changed, result.removed) == ([], [])
    assert len(rows(db_dsns["admin"])) == 8


def test_changed_procedure_gets_new_version(db_dsns, tmp_path):
    text = PROCEDURES_FILE.read_text("utf-8").replace(
        'name: WNORD1W, kind: SID, runway: "27", valid_from: 2026-11-05, valid_to: null,\n'
        '     airac: "2611"',
        'name: WNORD1W, kind: SID, runway: "27", valid_from: 2026-11-05, valid_to: null,\n'
        '     airac: "2612"',
    )
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_procedures(c, procedures())
        assert load_procedures(c, procedures(text, tmp_path)).changed == ["WNORD1W"]
    wnord = [r for r in rows(db_dsns["admin"]) if r[0] == "WNORD1W"]
    assert wnord == [("WNORD1W", "2611", False), ("WNORD1W", "2612", True)]


def test_removed_procedure_is_superseded(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_procedures(c, procedures())
        result = load_procedures(c, [p for p in procedures() if p.name != "WSUED1E"])
    assert result.removed == ["WSUED1E"]
    assert ("WSUED1E", "2611", False) in rows(db_dsns["admin"])
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/db/test_analysis_procedures.py -v`
Expected: FAIL mit `ImportError: cannot import name 'load_procedures'`.

- [ ] **Step 3: Implementierung** – in `analysis/src/analysis/procedures.py`:

Importe ergänzen (Block der Drittanbieter-Importe):

```python
import psycopg
import yaml
from psycopg.types.json import Jsonb
```

Nach der Klasse `Procedure` einfügen:

```python
@dataclass(frozen=True)
class ProcedureSync:
    changed: list[str]
    removed: list[str]
```

Am Dateiende anhängen:

```python
_CURRENT = """
SELECT id, content_hash FROM procedures
WHERE name = %(name)s AND valid_from = %(valid_from)s AND superseded_at IS NULL
"""

_INSERT = """
INSERT INTO procedures (name, kind, runway, runway_heading_deg, direction, sector, airac,
  valid_from, valid_to, source, geom, waypoints, constraints, content_hash)
VALUES (%(name)s, %(kind)s, %(runway)s, %(runway_heading_deg)s, %(direction)s, %(sector)s,
  %(airac)s, %(valid_from)s, %(valid_to)s, %(source)s, ST_GeomFromEWKT(%(ewkt)s),
  %(waypoints)s, %(constraints)s, %(content_hash)s)
"""


def load_procedures(conn: psycopg.Connection, procedures: list[Procedure]) -> ProcedureSync:
    """Gleicht alle Verfahren in einer Transaktion ab; fehlende Verfahren werden geschlossen."""
    changed: list[str] = []
    with conn.transaction():
        for p in procedures:
            content_hash = p.content_hash()
            params = {
                "name": p.name,
                "kind": p.kind,
                "runway": p.runway,
                "runway_heading_deg": p.runway_heading_deg,
                "direction": p.direction,
                "sector": p.sector,
                "airac": p.airac,
                "valid_from": p.valid_from,
                "valid_to": p.valid_to,
                "source": p.source,
                "ewkt": "SRID=4326;LINESTRING("
                + ", ".join(f"{lon} {lat}" for lat, lon in p.line)
                + ")",
                "waypoints": Jsonb(list(p.waypoints)),
                "constraints": Jsonb(p.constraints),
                "content_hash": content_hash,
            }
            current = conn.execute(_CURRENT, params).fetchone()
            if current and current[1] == content_hash:
                continue
            if current:
                conn.execute(
                    "UPDATE procedures SET superseded_at = now() WHERE id = %s", (current[0],)
                )
            conn.execute(_INSERT, params)
            changed.append(p.name)
        keep = [(p.name, p.valid_from) for p in procedures]
        removed = conn.execute(
            "UPDATE procedures SET superseded_at = now()"
            " WHERE superseded_at IS NULL AND NOT ((name, valid_from) IN"
            " (SELECT * FROM unnest(%s::text[], %s::date[])))"
            " RETURNING name",
            ([k[0] for k in keep], [k[1] for k in keep]),
        ).fetchall()
    return ProcedureSync(changed, sorted(r[0] for r in removed))
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/db/test_analysis_procedures.py tests/analysis/test_procedures.py -v`
Expected: alle PASS.

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/procedures.py tests/db/test_analysis_procedures.py
git commit -m "analysis: Verfahren in der Datenbank versionieren"
```

---

### Task 6: Rolle `role` und Betriebsrichtung `direction`

**Files:**
- Create: `analysis/src/analysis/role.py`, `analysis/src/analysis/direction.py`
- Modify: `analysis/src/analysis/classify.py` (`_vertical_rate` → `vertical_rate`)
- Test: `tests/analysis/test_role.py`, `tests/analysis/test_direction.py`

**Interfaces:**
- Consumes: `geo` (Task 3), `procedures.direction_class` (Task 4), `events.sector` (M3), `segment.Point` (M3), `synthetic.routes` (Task 4)
- Produces:
  - `classify.vertical_rate(points: list[Point]) -> tuple[float, str]` (bisher privat, unverändert)
  - `role.Role(role: str, ref_ts: datetime, outward: list[XY], sector: str)` – `outward`: Spur vom Flughafen weg (Abflug ab Teilbeginn, Anflug rückwärts ab Teilende)
  - `role.determine_role(points: list[Point], local: Local, *, ber_radius_m: float, near_m: float, max_alt_ft: float, vrate_fpm: float) -> Role | None`
  - `direction.WINDOW = timedelta(minutes=30)`; `direction.window_start(ts: datetime) -> datetime`
  - `direction.flight_heading(role: Role, *, near_m: float, dist_m: float) -> float | None`
  - `direction.vote(heading: float | None, runway_headings: list[float], *, tol_deg: float) -> str | None`
  - `direction.WindowDirection(direction: str, n_flights: int, share: float | None, basis: str)`; `direction.decide(votes: list[str], *, min_flights: int, min_share: float) -> WindowDirection`

Festlegungen zur Spezifikation 5.2/5.3: Der „Teil innerhalb des BER-Radius“ reicht von der ersten bis zur letzten Position innerhalb. Die mittlere Vertikalrate rechnet wie die M3-Einstufung (Mittel der `baro_rate`, sonst Höhendifferenz). Der Bezugskurs verbindet die Spurpunkte am Rand von `ANALYSIS_ROLE_NEAR_M` und bei `ANALYSIS_DIRECTION_DIST_M` (linear interpoliert), in Flugrichtung. Die Stimme richtet sich nach dem nächstgelegenen Startbahnkurs; `n_flights` zählt Stimmen; `share` ist der Anteil der Mehrheit (ohne Stimmen `NULL`). Der Sektor des Flugs ist die Richtung vom Referenzpunkt zum Punkt, an dem die Spur den BER-Radius verlässt (Abflug) bzw. betritt (Anflug); ohne Austritt die letzte bzw. erste Position.

- [ ] **Step 1: Tests schreiben**

`tests/analysis/test_role.py` (Anflug: 45,4 km STAR + 14,5 km Endanflug bei 180 kt = 646,8 s ergeben 647 Positionen, die letzte bei x = 1576 m in 11000 − 646 × 1000/60 = 233 ft):

```python
from datetime import UTC, datetime, timedelta

import pytest
from synthetic.routes import (
    LOCAL,
    ONMID,
    ONORD,
    TEAST,
    THR_09,
    THR_27,
    TWEST,
    WNMID,
    WNORD,
    fly,
    points,
)

from analysis.role import determine_role

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
LIMITS = {"ber_radius_m": 40000.0, "near_m": 10000.0, "max_alt_ft": 3000, "vrate_fpm": 300.0}


def role_of(rows):
    return determine_role(points(rows), LOCAL, **LIMITS)


def test_departure():
    r = role_of(fly([THR_09, TWEST, WNMID, WNORD], T0))
    assert (r.role, r.ref_ts, r.sector) == ("departure", T0, "NW")
    assert r.outward[0] == (pytest.approx(-1500), pytest.approx(0, abs=1e-6))


def test_arrival():
    # 647 Positionen, letzte bei x = 1576 m in 233 ft
    rows = fly([ONORD, ONMID, TEAST, THR_27], T0, speed_kt=180, alt_ft=11000, vrate_fpm=-1000)
    r = role_of(rows)
    assert (r.role, r.ref_ts, r.sector) == ("arrival", T0 + timedelta(seconds=646), "NO")
    assert r.outward[0] == (pytest.approx(1576.48, abs=0.01), pytest.approx(0, abs=1e-6))


def test_level_overflight_has_no_role():
    assert role_of(fly([(-30000, 2000), (30000, 2000)], T0, alt_ft=2000, vrate_fpm=0)) is None


def test_departure_must_start_near_and_low():
    assert role_of(fly([(-12000, 0), (-40000, 0)], T0)) is None  # beginnt 12 km entfernt
    assert role_of(fly([THR_09, (-40000, 0)], T0, alt_ft=3500)) is None


def test_weak_climb_is_no_departure():
    assert role_of(fly([THR_09, (-40000, 0)], T0, vrate_fpm=200)) is None


def test_flight_outside_radius_has_no_role():
    assert role_of(fly([(-60000, 0), (-45000, 0)], T0)) is None
```

`tests/analysis/test_direction.py`:

```python
from datetime import UTC, datetime

import pytest

from analysis.direction import decide, flight_heading, vote, window_start
from analysis.role import Role

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
NEAR = {"near_m": 10000.0, "dist_m": 15000.0}


def test_window_start():
    assert window_start(datetime(2026, 11, 9, 14, 29, 59, tzinfo=UTC)) == T0
    assert window_start(datetime(2026, 11, 9, 14, 30, tzinfo=UTC)) == T0.replace(minute=30)


def test_heading_of_departure_and_arrival():
    west = [(-1500.0, 0.0), (-20000.0, 0.0)]
    dep = Role("departure", T0, west, "W")
    arr = Role("arrival", T0, west, "W")  # rückwärts: Anflug von Westen nach Osten
    assert flight_heading(dep, **NEAR) == pytest.approx(270.0)
    assert flight_heading(arr, **NEAR) == pytest.approx(90.0)


def test_heading_needs_direction_distance():
    short = Role("departure", T0, [(-1500.0, 0.0), (-14000.0, 0.0)], "W")
    assert flight_heading(short, **NEAR) is None


@pytest.mark.parametrize(
    "heading, expected", [(265, "west"), (300, "west"), (301, None), (80, "east"), (None, None)]
)
def test_vote(heading, expected):
    assert vote(heading, [270.0, 90.0], tol_deg=30) == expected


def test_vote_without_runways():
    assert vote(270, [], tol_deg=30) is None


@pytest.mark.parametrize(
    "votes, direction, share",
    [
        (["west"] * 5, "west", 1.0),  # klare Mehrheit
        (["west"] * 4 + ["east"], "west", 0.8),  # knapp
        (["west"] * 3 + ["east"], "unknown", 0.75),  # zu knapp
        (["east"] * 2, "unknown", 1.0),  # zu wenige Flüge
        ([], "unknown", None),
    ],
)
def test_decide(votes, direction, share):
    d = decide(votes, min_flights=3, min_share=0.8)
    assert (d.direction, d.n_flights, d.share) == (direction, len(votes), share)
    assert d.basis.startswith(f"{len(votes)} Stimmen")
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_role.py tests/analysis/test_direction.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis.role'`.

- [ ] **Step 3: Implementierung**

In `analysis/src/analysis/classify.py` `_vertical_rate` in `vertical_rate` umbenennen (Definition und Aufruf in `classify`).

`analysis/src/analysis/role.py`:

```python
"""Rolle eines Flugs bezogen auf BER: Abflug, Anflug oder keine (ohne Datenbank)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from analysis.classify import vertical_rate
from analysis.events import sector
from analysis.geo import XY, Local, azimuth_deg, exit_point
from analysis.segment import Point


@dataclass(frozen=True)
class Role:
    role: str  # departure | arrival
    ref_ts: datetime  # Startzeit bzw. Landezeit: erste bzw. letzte Position des Teils
    outward: list[XY]  # Spur vom Flughafen weg: Abflug ab Teilbeginn, Anflug rückwärts
    sector: str  # Sektor beim Verlassen bzw. Betreten des BER-Radius


def determine_role(
    points: list[Point],
    local: Local,
    *,
    ber_radius_m: float,
    near_m: float,
    max_alt_ft: float,
    vrate_fpm: float,
) -> Role | None:
    """Betrachtet den Teil der Spur innerhalb ``ber_radius_m`` (erste bis letzte Position
    darin). Abflug: Teil beginnt näher als ``near_m`` unterhalb ``max_alt_ft`` und steigt im
    Mittel stärker als ``vrate_fpm``. Anflug spiegelbildlich am Ende des Teils mit Sinken."""
    xy = [local.xy(p.lat, p.lon) for p in points]
    inside = [i for i, q in enumerate(xy) if math.hypot(*q) < ber_radius_m]
    if not inside:
        return None
    i0, i1 = inside[0], inside[-1]
    part = [p for p in points[i0 : i1 + 1] if p.alt_ft is not None]
    if len(part) < 2:
        return None
    rate, _ = vertical_rate(part)

    def low_and_near(i: int) -> bool:
        p = points[i]
        return p.alt_ft is not None and p.alt_ft < max_alt_ft and math.hypot(*xy[i]) < near_m

    if rate > vrate_fpm and low_and_near(i0):
        role, ref_ts, outward = "departure", points[i0].ts, xy[i0:]
    elif rate < -vrate_fpm and low_and_near(i1):
        role, ref_ts, outward = "arrival", points[i1].ts, xy[: i1 + 1][::-1]
    else:
        return None
    edge = exit_point(outward, ber_radius_m) or outward[-1]
    return Role(role, ref_ts, outward, sector(azimuth_deg((0.0, 0.0), edge)))
```

`analysis/src/analysis/direction.py`:

```python
"""Betriebsrichtung: Stimme je Flug und Mehrheit je 30-Minuten-Fenster (ohne Datenbank)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from analysis.geo import angle_diff, azimuth_deg, exit_point
from analysis.procedures import direction_class
from analysis.role import Role

WINDOW = timedelta(minutes=30)


def window_start(ts: datetime) -> datetime:
    """Beginn des 30-Minuten-Fensters (UTC, auf :00 bzw. :30 ausgerichtet)."""
    epoch = int(ts.timestamp()) // 1800 * 1800
    return datetime.fromtimestamp(epoch, UTC)


def flight_heading(role: Role, *, near_m: float, dist_m: float) -> float | None:
    """Bezugskurs: zwischen den Spurpunkten am Rand von ``near_m`` und bei ``dist_m``,
    in Flugrichtung. ``None``, wenn die Spur ``dist_m`` nicht erreicht."""
    a = exit_point(role.outward, near_m)
    b = exit_point(role.outward, dist_m)
    if a is None or b is None or a == b:
        return None
    return azimuth_deg(a, b) if role.role == "departure" else azimuth_deg(b, a)


def vote(heading: float | None, runway_headings: list[float], *, tol_deg: float) -> str | None:
    """``west``/``east`` nach dem nächsten Startbahnkurs, wenn höchstens ``tol_deg`` entfernt."""
    if heading is None or not runway_headings:
        return None
    nearest = min(runway_headings, key=lambda r: angle_diff(heading, r))
    if angle_diff(heading, nearest) > tol_deg:
        return None
    return direction_class(nearest)


@dataclass(frozen=True)
class WindowDirection:
    direction: str  # west | east | unknown
    n_flights: int  # Stimmen im Fenster
    share: float | None  # Anteil der Mehrheit
    basis: str


def decide(votes: list[str], *, min_flights: int, min_share: float) -> WindowDirection:
    counts = Counter(votes)
    n = len(votes)
    basis = f"{n} Stimmen: {counts['west']} west, {counts['east']} east"
    if n == 0:
        return WindowDirection("unknown", 0, None, basis)
    leader, top = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    share = top / n
    if n >= min_flights and share >= min_share:
        return WindowDirection(leader, n, share, basis)
    return WindowDirection("unknown", n, share, basis)
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/analysis -v`
Expected: alle PASS (`test_role.py`: 6, `test_direction.py`: 14, `test_classify.py` unverändert grün).

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/role.py analysis/src/analysis/direction.py analysis/src/analysis/classify.py tests/analysis/test_role.py tests/analysis/test_direction.py
git commit -m "analysis: Rolle und Betriebsrichtung von An- und Abflügen"
```

---

### Task 7: Abweichung, Annäherung und Prüffall `deviation`

**Files:**
- Create: `analysis/src/analysis/deviation.py`
- Test: `tests/analysis/test_deviation.py`

**Interfaces:**
- Consumes: `geo.project`, `geo.distance_to_line`, `geo.Local`, `geo.XY` (Task 3), `segment.Point`
- Produces:
  - `CONFIDENCE_LABEL = {"high": "hoch", "medium": "mittel", "low": "niedrig", "none": "keine"}`
  - `Sample(ts: datetime, xy: XY, alt_ft: int | None)`; `samples(points: list[Point], local: Local) -> list[Sample]`
  - `section(track: list[Sample], line: list[XY], max_alt_ft: int | None) -> list[tuple[Sample, float]]` (Geltungsabschnitt mit seitlichem Abstand)
  - `Corridor(eval_from, eval_to, max_dev_m, outside_s, outside_m, deviation: bool, max_position_gap_s)`; `corridor(sec, *, half_width_m: float, min_s: float) -> Corridor` (mindestens zwei Positionen)
  - `Approach(geofence_id: int | None, min_dist_ref_m, proc_dist_ref_m, approach: bool)`; `approach(track: list[XY], line: list[XY], zones: list[tuple[int, XY]], *, tol_m: float) -> Approach`
  - `review(*, deviation, approach, confidence, in_reception_gap: bool | None, max_position_gap_s: float | None, max_gap_s: float, relevant_event: bool) -> tuple[bool, list[str]]`

Festlegungen: Annäherung (B) betrachtet die Spur im Geltungsabschnitt (als Linie zwischen den Positionen), damit Flug und Ideallinie über dieselbe Strecke verglichen werden. `review_reasons` enthält alle erfüllten Bedingungen in fester Reihenfolge: `Abweichung`, `Annäherung`, `Sicherheit hoch|mittel`, `Datenqualität ausreichend`, `relevanter Überflug`. Fehlende Lückenangabe gilt als nicht ausreichend.

- [ ] **Step 1: Tests schreiben** – `tests/analysis/test_deviation.py`. Rechenweg der Korridortests (Linie entlang x, 100 m/s, Versatz 2500 m sprunghaft): Austritt bei t = 49 + 1852/2500 = 49,7408 s, Rückkehr bei t = 89 + 648/2500 = 89,2592 s → 39,5184 s außerhalb; Strecke 2 × 2502,0 m × 0,2592 + 39 × 100 m = 5197,04 m.

```python
from datetime import UTC, datetime, timedelta

import pytest

from analysis.deviation import Sample, approach, corridor, review, section

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
LINE = [(0.0, 0.0), (20000.0, 0.0)]
W = {"half_width_m": 1852.0, "min_s": 30.0}


def track(offset, n=140, x0=1000.0, alt=lambda t: 3000):
    """Je Sekunde 100 m nach Osten, seitlicher Versatz ``offset(t)``."""
    return [
        Sample(T0 + timedelta(seconds=t), (x0 + 100.0 * t, offset(t)), alt(t)) for t in range(n)
    ]


def test_long_excursion_is_deviation():
    # 2500 m Versatz von t=50 bis t=89; Austritt bei 49 + 1852/2500, Rückkehr bei 89 + 648/2500
    c = corridor(section(track(lambda t: 2500.0 if 50 <= t < 90 else 0.0), LINE, None), **W)
    assert c.deviation is True
    assert c.outside_s == pytest.approx(39.5184)
    assert c.outside_m == pytest.approx(5197.04, abs=0.01)
    assert (c.max_dev_m, c.max_position_gap_s) == (2500.0, 1.0)
    assert (c.eval_from, c.eval_to) == (T0, T0 + timedelta(seconds=139))


def test_short_overshoot_is_no_deviation():
    c = corridor(section(track(lambda t: 2500.0 if 50 <= t < 70 else 0.0), LINE, None), **W)
    assert c.deviation is False
    assert c.outside_s == pytest.approx(19.5184)


def test_section_starting_outside():
    c = corridor(section(track(lambda t: 2500.0 if t < 40 else 0.0), LINE, None), **W)
    assert c.deviation is True
    assert c.outside_s == pytest.approx(39.2592)
    assert c.outside_m == pytest.approx(4548.52, abs=0.01)


def test_section_is_limited_to_line_extent():
    sec = section(track(lambda t: 0.0, n=300, x0=-5000.0), LINE, None)
    assert len(sec) == 201  # x = 0 … 20000 m
    assert (sec[0][0].xy, sec[-1][0].xy) == ((0.0, 0.0), (20000.0, 0.0))


def test_section_altitude_limit():
    sec = section(track(lambda t: 0.0, alt=lambda t: 2000 + 20 * t), LINE, 3000)
    assert len(sec) == 51 and sec[-1][0].alt_ft == 3000
    no_alt = section(track(lambda t: 0.0, alt=lambda t: None), LINE, 3000)
    assert no_alt == []


def test_approach_picks_zone_with_smallest_difference():
    flight = [(float(x), -2500.0 if 9000 <= x <= 11000 else 0.0) for x in range(0, 20001, 100)]
    zones = [(1, (10000.0, 8000.0)), (2, (10000.0, -3000.0))]
    a = approach(flight, LINE, zones, tol_m=1852)
    assert (a.geofence_id, a.min_dist_ref_m, a.proc_dist_ref_m, a.approach) == (2, 500, 3000, True)


def test_no_approach_on_the_line():
    flight = [(float(x), 0.0) for x in range(0, 20001, 100)]
    a = approach(flight, LINE, [(2, (10000.0, -3000.0))], tol_m=1852)
    assert (a.min_dist_ref_m, a.approach) == (3000, False)
    assert approach(flight, LINE, [], tol_m=1852).geofence_id is None


GOOD = {
    "deviation": True,
    "approach": False,
    "confidence": "high",
    "in_reception_gap": False,
    "max_position_gap_s": 5.0,
    "max_gap_s": 30.0,
    "relevant_event": True,
}


def test_review_when_all_conditions_hold():
    assert review(**GOOD) == (
        True,
        ["Abweichung", "Sicherheit hoch", "Datenqualität ausreichend", "relevanter Überflug"],
    )


@pytest.mark.parametrize(
    "change",
    [
        {"deviation": False},
        {"confidence": "low"},
        {"in_reception_gap": True},
        {"in_reception_gap": None},
        {"max_position_gap_s": 31.0},
        {"relevant_event": False},
    ],
)
def test_no_review_if_one_condition_fails(change):
    flagged, _ = review(**(GOOD | change))
    assert flagged is False


def test_review_by_approach_with_medium_confidence():
    flagged, reasons = review(
        **(GOOD | {"deviation": False, "approach": True, "confidence": "medium"})
    )
    assert flagged is True and reasons[:2] == ["Annäherung", "Sicherheit mittel"]
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_deviation.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis.deviation'`.

- [ ] **Step 3: Implementierung** – `analysis/src/analysis/deviation.py`:

```python
"""Abweichung vom Korridor (C), Annäherung an Zonen (B) und Prüffall (E), ohne Datenbank."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from analysis.geo import XY, Local, distance_to_line, project
from analysis.segment import Point

CONFIDENCE_LABEL = {"high": "hoch", "medium": "mittel", "low": "niedrig", "none": "keine"}


@dataclass(frozen=True)
class Sample:
    ts: datetime
    xy: XY
    alt_ft: int | None


def samples(points: list[Point], local: Local) -> list[Sample]:
    return [Sample(p.ts, local.xy(p.lat, p.lon), p.alt_ft) for p in points]


def section(
    track: list[Sample], line: list[XY], max_alt_ft: int | None
) -> list[tuple[Sample, float]]:
    """Geltungsabschnitt: Positionen, deren Lotfußpunkt zwischen Anfang und Ende der Linie
    liegt (bei gesetzter Höhengrenze nur bis zu dieser Höhe), mit seitlichem Abstand."""
    out = []
    for s in track:
        if max_alt_ft is not None and (s.alt_ft is None or s.alt_ft > max_alt_ft):
            continue
        pr = project(s.xy, line)
        if pr.within:
            out.append((s, pr.dist_m))
    return out


@dataclass(frozen=True)
class Corridor:
    eval_from: datetime
    eval_to: datetime
    max_dev_m: float
    outside_s: float
    outside_m: float
    deviation: bool
    max_position_gap_s: float


def corridor(sec: list[tuple[Sample, float]], *, half_width_m: float, min_s: float) -> Corridor:
    """Außerhalb-Abschnitte aus aufeinanderfolgenden Positionen; Ein- und Austritt linear
    zwischen zwei Positionen interpoliert. Voraussetzung: mindestens zwei Positionen."""
    w = half_width_m
    spans: list[list] = []  # [Beginn, Ende, Strecke m]
    first, d_first = sec[0]
    if d_first > w:
        spans.append([first.ts, first.ts, 0.0])
    gaps = []
    for (a, da), (b, db) in zip(sec, sec[1:], strict=False):
        dt = (b.ts - a.ts).total_seconds()
        gaps.append(dt)
        seg = math.dist(a.xy, b.xy)
        if da > w and db > w:
            spans[-1][1] = b.ts
            spans[-1][2] += seg
        elif da <= w < db:
            f = (w - da) / (db - da)
            spans.append([a.ts + timedelta(seconds=f * dt), b.ts, seg * (1 - f)])
        elif db <= w < da:
            f = (da - w) / (da - db)
            spans[-1][1] = a.ts + timedelta(seconds=f * dt)
            spans[-1][2] += seg * f
    durations = [(end - start).total_seconds() for start, end, _ in spans]
    return Corridor(
        eval_from=first.ts,
        eval_to=sec[-1][0].ts,
        max_dev_m=max(d for _, d in sec),
        outside_s=sum(durations),
        outside_m=sum(m for _, _, m in spans),
        deviation=any(d >= min_s for d in durations),
        max_position_gap_s=max(gaps),
    )


@dataclass(frozen=True)
class Approach:
    geofence_id: int | None
    min_dist_ref_m: float | None
    proc_dist_ref_m: float | None
    approach: bool


def approach(
    track: list[XY], line: list[XY], zones: list[tuple[int, XY]], *, tol_m: float
) -> Approach:
    """Für jede Zone kleinster Abstand von Spur und Ideallinie zum Referenzpunkt; maßgeblich
    ist die Zone mit der kleinsten Differenz Spur − Ideallinie."""
    best: Approach | None = None
    for gid, ref in zones:
        flight = distance_to_line(ref, track)
        ideal = distance_to_line(ref, line)
        if best is None or flight - ideal < best.min_dist_ref_m - best.proc_dist_ref_m:
            best = Approach(gid, flight, ideal, flight - ideal < -tol_m)
    return best or Approach(None, None, None, False)


def review(
    *,
    deviation: bool,
    approach: bool,
    confidence: str,
    in_reception_gap: bool | None,
    max_position_gap_s: float | None,
    max_gap_s: float,
    relevant_event: bool,
) -> tuple[bool, list[str]]:
    """Prüffall, wenn alle Bedingungen gelten; liefert zusätzlich die erfüllten Bedingungen."""
    trigger = deviation or approach
    rated = confidence in ("high", "medium")
    quality = (
        in_reception_gap is False
        and max_position_gap_s is not None
        and max_position_gap_s <= max_gap_s
    )
    reasons = []
    if deviation:
        reasons.append("Abweichung")
    if approach:
        reasons.append("Annäherung")
    if rated:
        reasons.append(f"Sicherheit {CONFIDENCE_LABEL[confidence]}")
    if quality:
        reasons.append("Datenqualität ausreichend")
    if relevant_event:
        reasons.append("relevanter Überflug")
    return trigger and rated and quality and relevant_event, reasons
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/analysis/test_deviation.py -v`
Expected: 15 PASS.

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/deviation.py tests/analysis/test_deviation.py
git commit -m "analysis: Korridor, Annäherung und Prüffall"
```

---

### Task 8: Zuordnung `assign`

**Files:**
- Create: `analysis/src/analysis/assign.py`
- Test: `tests/analysis/test_assign.py`

**Interfaces:**
- Consumes: `deviation.Sample`, `deviation.section`, `deviation.samples` (Task 7), `events.SECTORS` (M3), `synthetic.routes` (Task 4)
- Produces:
  - `KIND_FOR_ROLE = {"departure": "SID", "arrival": "STAR"}`
  - `Reference(id: int, name, kind, direction, sector, line: list[XY], valid_from: date, valid_to: date | None)` mit `valid_on(day: date) -> bool` (`[valid_from, valid_to)`)
  - `Assignment(reference: Reference | None, confidence: str, basis: str, mean_dev_m: float | None, second_mean_dev_m: float | None)`
  - `sector_fit(flight: str, procedure: str) -> str | None` (`genau`/`ungefähr`/`None`)
  - `assign(role, direction, flight_sector, track: list[Sample], references: list[Reference], *, max_alt_ft: int | None, ratio: float) -> Assignment`

Festlegungen: Kandidat ist nur, wer im Geltungsabschnitt mindestens zwei Positionen hat (sonst ist keine mittlere Abweichung bestimmbar). `basis` besteht aus je einem Satz für Betriebsrichtung, Sektor und Geometrie (bzw. „Kein … passt …“).

- [ ] **Step 1: Tests schreiben** – `tests/analysis/test_assign.py`:

```python
from datetime import UTC, date, datetime

import pytest
from synthetic.routes import LOCAL, THR_09, TWEST, WNMID, WNORD, WSMID, WSUED, fly, points

from analysis.assign import Reference, assign, sector_fit
from analysis.deviation import samples

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
D0 = date(2026, 11, 5)


def ref(rid, name, line, *, kind="SID", direction="west", sector="NW", valid_to=None):
    return Reference(rid, name, kind, direction, sector, line, D0, valid_to)


NORTH = ref(1, "WNORD1W", [THR_09, TWEST, WNMID, WNORD])
SOUTH = ref(2, "WSUED1W", [THR_09, TWEST, WSMID, WSUED], sector="SW")
EAST = ref(3, "ONORD1E", [(1500.0, 0.0), (12000.0, 0.0)], direction="east", sector="NO")
STAR = ref(4, "ONORD1W", [(35000.0, 40000.0), (12000.0, 0.0)], kind="STAR", sector="NO")
ALL = [NORTH, SOUTH, EAST, STAR]
OPTS = {"max_alt_ft": None, "ratio": 2.0}


def north_track(offset_m=0.0):
    """Abflug entlang WNORD1W, um ``offset_m`` nach Norden versetzt."""
    shifted = [(x, y + offset_m) for x, y in [THR_09, TWEST, WNMID, WNORD]]
    return samples(points(fly(shifted, T0)), LOCAL)


def test_sector_fit():
    assert sector_fit("N", "N") == "genau"
    assert sector_fit("N", "NW") == sector_fit("N", "NO") == "ungefähr"
    assert sector_fit("N", "S") is None


def test_high_confidence():
    a = assign("departure", "west", "NW", north_track(), ALL, **OPTS)
    assert (a.reference.name, a.confidence) == ("WNORD1W", "high")
    assert a.mean_dev_m == pytest.approx(0, abs=1e-6)
    assert a.second_mean_dev_m is None  # WSUED1W liegt in SW, kein Nachbarsektor von NW
    assert a.basis == (
        "Betriebsrichtung west. Sektor NW, Verfahren WNORD1W NW: passt genau."
        " Mittlere Abweichung 0 m, kein weiteres Verfahren in Frage."
    )


def test_high_with_distinct_second_candidate():
    upper = ref(5, "OBEN1W", [(-1500.0, 3000.0), (-50000.0, 3000.0)], sector="W")
    lower = ref(6, "UNTEN1W", [(-1500.0, 0.0), (-50000.0, 0.0)], sector="W")
    track = samples(points(fly([(-2000.0, 400.0), (-30000.0, 400.0)], T0)), LOCAL)
    a = assign("departure", "west", "W", track, [upper, lower], **OPTS)
    assert (a.reference.name, a.confidence) == ("UNTEN1W", "high")
    assert (a.mean_dev_m, a.second_mean_dev_m) == (pytest.approx(400), pytest.approx(2600))
    assert "OBEN1W 2600 m (deutlich getrennt)" in a.basis


def test_medium_when_direction_unknown():
    a = assign("departure", "unknown", "NW", north_track(), ALL, **OPTS)
    assert (a.reference.name, a.confidence) == ("WNORD1W", "medium")
    assert "Betriebsrichtung unbekannt" in a.basis


def test_medium_when_sector_only_neighbouring():
    a = assign("departure", "west", "N", north_track(), ALL, **OPTS)
    assert (a.reference.name, a.confidence, a.second_mean_dev_m) == ("WNORD1W", "medium", None)
    assert "passt ungefähr" in a.basis


def test_medium_when_candidates_not_distinct():
    upper = ref(5, "OBEN1W", [(-1500.0, 1000.0), (-50000.0, 1000.0)], sector="W")
    lower = ref(6, "UNTEN1W", [(-1500.0, 0.0), (-50000.0, 0.0)], sector="W")
    track = samples(points(fly([(-2000.0, 400.0), (-30000.0, 400.0)], T0)), LOCAL)
    a = assign("departure", "west", "W", track, [upper, lower], **OPTS)
    assert (a.reference.name, a.confidence) == ("UNTEN1W", "medium")
    assert (a.mean_dev_m, a.second_mean_dev_m) == (pytest.approx(400), pytest.approx(600))
    assert "nicht deutlich getrennt" in a.basis


def test_low_when_two_conditions_fail():
    a = assign("departure", "unknown", "N", north_track(), ALL, **OPTS)
    assert (a.reference.name, a.confidence) == ("WNORD1W", "low")


def test_none_without_candidate():
    a = assign("arrival", "east", "NO", north_track(), ALL, **OPTS)
    assert (a.reference, a.confidence, a.mean_dev_m) == (None, "none", None)
    assert "Kein STAR passt" in a.basis


def test_reference_without_section_is_no_candidate():
    far = ref(7, "FERN1W", [(-60000.0, 0.0), (-90000.0, 0.0)], sector="NW")
    assert assign("departure", "west", "NW", north_track(), [far], **OPTS).confidence == "none"


def test_altitude_limit_applies_to_assignment():
    a = assign("departure", "west", "NW", north_track(), [NORTH], max_alt_ft=400, ratio=2.0)
    assert a.confidence == "none"  # Spur beginnt in 500 ft


def test_valid_on():
    old = ref(8, "ALT1W", NORTH.line, valid_to=date(2026, 11, 9))
    assert old.valid_on(date(2026, 11, 8)) and not old.valid_on(date(2026, 11, 9))
    assert not old.valid_on(date(2026, 11, 4))
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_assign.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis.assign'`.

- [ ] **Step 3: Implementierung** – `analysis/src/analysis/assign.py`:

```python
"""Zuordnung Flug → Verfahren mit Sicherheitsstufe und Begründung (ohne Datenbank)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import fmean

from analysis.deviation import Sample, section
from analysis.events import SECTORS
from analysis.geo import XY

KIND_FOR_ROLE = {"departure": "SID", "arrival": "STAR"}
_LEVELS = ("high", "medium", "low")


@dataclass(frozen=True)
class Reference:
    """Gültige Fassung eines Verfahrens, Ideallinie in der lokalen Ebene."""

    id: int
    name: str
    kind: str
    direction: str
    sector: str
    line: list[XY]
    valid_from: date
    valid_to: date | None

    def valid_on(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day < self.valid_to)


@dataclass(frozen=True)
class Assignment:
    reference: Reference | None
    confidence: str  # high | medium | low | none
    basis: str
    mean_dev_m: float | None
    second_mean_dev_m: float | None


def sector_fit(flight: str, procedure: str) -> str | None:
    """``genau`` bei gleichem Sektor, ``ungefähr`` beim Nachbarsektor, sonst ``None``."""
    if flight == procedure:
        return "genau"
    step = (SECTORS.index(flight) - SECTORS.index(procedure)) % len(SECTORS)
    return "ungefähr" if step in (1, len(SECTORS) - 1) else None


def assign(
    role: str,
    direction: str,
    flight_sector: str,
    track: list[Sample],
    references: list[Reference],
    *,
    max_alt_ft: int | None,
    ratio: float,
) -> Assignment:
    kind = KIND_FOR_ROLE[role]
    sentences = [
        f"Betriebsrichtung {direction}."
        if direction != "unknown"
        else "Betriebsrichtung unbekannt, Verfahren beider Richtungen geprüft."
    ]
    scored: list[tuple[float, Reference, str]] = []
    for ref in references:
        if ref.kind != kind or (direction != "unknown" and ref.direction != direction):
            continue
        fit = sector_fit(flight_sector, ref.sector)
        if fit is None:
            continue
        sec = section(track, ref.line, max_alt_ft)
        if len(sec) < 2:
            continue
        scored.append((fmean(d for _, d in sec), ref, fit))
    if not scored:
        sentences.append(
            f"Kein {kind} passt nach Richtung, Sektor {flight_sector} und Geltungsabschnitt."
        )
        return Assignment(None, "none", " ".join(sentences), None, None)

    scored.sort(key=lambda s: s[0])
    best, ref, fit = scored[0]
    second = scored[1] if len(scored) > 1 else None
    sentences.append(f"Sektor {flight_sector}, Verfahren {ref.name} {ref.sector}: passt {fit}.")
    if second is None:
        sentences.append(f"Mittlere Abweichung {best:.0f} m, kein weiteres Verfahren in Frage.")
        distinct = True
    else:
        distinct = second[0] >= ratio * best
        sentences.append(
            f"Mittlere Abweichung {best:.0f} m, nächstes Verfahren {second[1].name}"
            f" {second[0]:.0f} m ({'deutlich' if distinct else 'nicht deutlich'} getrennt)."
        )
    failed = (direction == "unknown") + (fit != "genau") + (not distinct)
    return Assignment(
        ref,
        _LEVELS[min(failed, 2)],
        " ".join(sentences),
        best,
        None if second is None else second[0],
    )
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/analysis/test_assign.py -v`
Expected: 11 PASS.

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/assign.py tests/analysis/test_assign.py
git commit -m "analysis: Zuordnung von Flügen zu Verfahren mit Sicherheitsstufe"
```

---

### Task 9: Routenschritt im Lauf `routes`

**Files:**
- Create: `analysis/src/analysis/routes.py`
- Modify: `analysis/src/analysis/pipeline.py`, `analysis/src/analysis/db.py`, `analysis/src/analysis/__init__.py`
- Test: `tests/db/test_analysis_routes.py`

**Interfaces:**
- Consumes: Tasks 3–8; `db.in_reception_gap`, `db.Counts` (M3); `sync_zones`, `run_once`, `rebuild` (M3)
- Produces:
  - `routes.RouteContext(local: Local, references: list[Reference], runway_headings: list[float], zones: list[tuple[int, XY]])`
  - `routes.enabled(cfg) -> bool` (Datei gesetzt und vorhanden)
  - `routes.load_context(conn, cfg) -> RouteContext` (nicht abgelöste Verfahren, Startbahnkurse, Referenzpunkte der aktuellen Zonen)
  - `routes.record_role(conn, run_id, flight_id, points, ctx, cfg) -> bool` (vorläufige Zeile in `flight_assessments`)
  - `routes.affected_windows(spans: list[tuple[datetime, datetime]]) -> set[datetime]`
  - `routes.update_directions(conn, run_id, windows: set[datetime], cfg) -> list[datetime]` (Fenster mit geänderter Richtung)
  - `routes.flight_points(conn, flight_id) -> list[Point]` (Spur aus `flights.track`, Höhe aus `positions`)
  - `routes.assess(conn, run_id, flight_id, ctx, cfg) -> None`
  - `routes.pending(conn, run_id, changed: list[datetime]) -> list[int]`
  - `routes.run_step(conn, cfg, run_id, ctx, spans, counts) -> None`
  - `db.Counts.assessments: int = 0`; `pipeline.RunResult.assessments: int = 0`
  - `pipeline.sync_procedures(cfg, path: Path) -> ProcedureSync`
  - `analysis.__version__ == "0.3.0"`

Ablauf im Lauf (eine Transaktion wie bisher):

1. Zu Beginn von `_process`: Ist `ANALYSIS_PROCEDURES_FILE` nicht gesetzt oder fehlt die Datei, wird eine Warnung protokolliert und der Routenschritt entfällt; Flüge und Überflüge entstehen weiter.
2. Je Flugzeug (Savepoint wie bisher): nach den Überflugereignissen erhält jeder neue Flug mit Rolle eine vorläufige Zeile (`ref_ts`, `ref_heading_deg`, `vote`, `flight_sector`, `confidence = 'none'`, `basis = 'noch nicht bewertet'`).
3. Nach allen Flugzeugen: Fenster, die die Zeiträume gelöschter oder neu gebildeter Flüge berühren, werden aus den Stimmen in `flight_assessments` neu berechnet.
4. Bewertet werden alle neuen Flüge dieses Laufs und alle Flüge in Fenstern mit geänderter Betriebsrichtung, je Flug mit Savepoint; ein Fehler zählt als `skipped`, die vorläufige Zeile bleibt stehen.

Für einen Flug gilt die nicht abgelöste Fassung, deren `[valid_from, valid_to)` das UTC-Datum des Flugbeginns enthält.

Testszenario (`tests/db/test_analysis_routes.py`, Zone „Testzone“ mit Radius 5000 m um (−26000, 6000), 8629 m neben WNORD1W): drei Abflüge, ein Abflug mit Umweg über (−23000, 6000) und ein Anflug, alle im Fenster 14:00–14:30 UTC. Erwartet: Richtung `west` mit 5 Stimmen; alle Zuordnungen `high`; nur der Umweg ist Abweichung (Umweg-Wegpunkt 5687 m neben der Linie, nächste Position 5658 m, 123 s außerhalb), Annäherung (3016 m statt 8629 m) und Prüffall. Die Nachlieferung kommt in einer zweiten Datei ab 14:20; die ersten beiden Flüge enden um 14:07:45 (466 Positionen), also vor dem Löschbereich ab 14:08 (14:20 − 120 s Settle − 600 s Pausenschwelle), und werden nur wegen der geänderten Richtung neu bewertet.

- [ ] **Step 1: Tests schreiben** – `tests/db/test_analysis_routes.py`:

```python
import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from synthetic.routes import (
    LOCAL,
    ONMID,
    ONORD,
    PROCEDURES_FILE,
    TEAST,
    THR_09,
    THR_27,
    TWEST,
    WNMID,
    WNORD,
    WSMID,
    WSUED,
    fly,
)
from synthetic.tracks import add_raw_file, insert_positions

from analysis.config import Config
from analysis.pipeline import rebuild, run_once, sync_procedures, sync_zones

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
NORTH = [THR_09, TWEST, WNMID, WNORD]
SOUTH = [THR_09, TWEST, WSMID, WSUED]
# Abflug, der vom WNORD1W abweicht und dabei die Zone streift
DETOUR = [THR_09, TWEST, (-23000.0, 6000.0), WNMID, WNORD]
ARRIVAL = [ONORD, ONMID, TEAST, THR_27]
ZONE_CENTER = (-26000.0, 6000.0)  # 8629 m neben WNORD1W, Radius 5000 m


def zones_geojson():
    lat, lon = LOCAL.latlon(*ZONE_CENTER)
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {"name": "Testzone", "radius_m": 5000},
                }
            ],
        }
    )


@pytest.fixture
def cfg(db_dsns, tmp_path):
    zones = tmp_path / "geofences.geojson"
    zones.write_text(zones_geojson(), encoding="utf-8")
    c = Config(
        db_dsn=db_dsns["analysis"],
        ber_lat=50.0,
        ber_lon=10.0,
        zones_file=zones,
        procedures_file=PROCEDURES_FILE,
    )
    sync_zones(c, zones)
    sync_procedures(c, PROCEDURES_FILE)
    return c


def departure(route, minutes, icao):
    return fly(route, T0 + timedelta(minutes=minutes), icao24=icao, callsign=f"TST{icao[-3:]}")


def arrival(minutes, icao):
    return fly(
        ARRIVAL,
        T0 + timedelta(minutes=minutes),
        speed_kt=180,
        alt_ft=11000,
        vrate_fpm=-1000,
        icao24=icao,
        callsign=f"TST{icao[-3:]}",
    )


def scenario(dsn):
    for rows in (
        departure(NORTH, 0, "ff0101"),
        departure(NORTH, 5, "ff0102"),
        departure(SOUTH, 10, "ff0103"),
        departure(DETOUR, 15, "ff0104"),
        arrival(5, "ff0105"),
    ):
        insert_positions(dsn, rows)
    add_raw_file(dsn, T0, T0 + timedelta(hours=1))


ASSESSMENTS = """
SELECT f.icao24, a.role, a.direction, a.flight_sector, p.name, a.confidence, a.deviation,
       a.approach, a.review, a.review_reasons
FROM flight_assessments a JOIN flights f ON f.id = a.flight_id
LEFT JOIN procedures p ON p.id = a.procedure_id ORDER BY f.icao24
"""


def q(dsn, sql, params=None):
    with psycopg.connect(dsn) as c:
        return c.execute(sql, params).fetchall()


def test_direction_assignment_and_review(db_dsns, cfg):
    scenario(db_dsns["admin"])

    result = run_once(cfg)

    assert (result.flights, result.assessments, result.skipped) == (5, 5, 0)
    assert q(
        db_dsns["reader"],
        "SELECT window_start, direction, n_flights, share FROM" " operating_directions",
    ) == [(T0, "west", 5, 1.0)]
    reasons = [
        "Abweichung",
        "Annäherung",
        "Sicherheit hoch",
        "Datenqualität ausreichend",
        "relevanter Überflug",
    ]
    assert q(db_dsns["reader"], ASSESSMENTS) == [
        (
            "ff0101",
            "departure",
            "west",
            "NW",
            "WNORD1W",
            "high",
            False,
            False,
            False,
            ["Sicherheit hoch", "Datenqualität ausreichend"],
        ),
        (
            "ff0102",
            "departure",
            "west",
            "NW",
            "WNORD1W",
            "high",
            False,
            False,
            False,
            ["Sicherheit hoch", "Datenqualität ausreichend"],
        ),
        (
            "ff0103",
            "departure",
            "west",
            "SW",
            "WSUED1W",
            "high",
            False,
            False,
            False,
            ["Sicherheit hoch", "Datenqualität ausreichend"],
        ),
        ("ff0104", "departure", "west", "NW", "WNORD1W", "high", True, True, True, reasons),
        (
            "ff0105",
            "arrival",
            "west",
            "NO",
            "ONORD1W",
            "high",
            False,
            False,
            False,
            ["Sicherheit hoch", "Datenqualität ausreichend"],
        ),
    ]
    ((max_dev, outside_s, min_ref, proc_ref, gap),) = q(
        db_dsns["reader"],
        "SELECT round(max_dev_m), round(outside_s), round(min_dist_ref_m),"
        " round(proc_dist_ref_m), max_position_gap_s FROM flight_assessments a"
        " JOIN flights f ON f.id = a.flight_id WHERE f.icao24 = 'ff0104'",
    )
    # Umweg-Wegpunkt 5687 m neben der Linie; nächste Position 5658 m; 15,9 km außerhalb
    assert (max_dev, outside_s, min_ref, proc_ref, gap) == (5658, 123, 3016, 8629, 1.0)


def test_late_flight_changes_direction_and_assessment(db_dsns, cfg):
    insert_positions(db_dsns["admin"], departure(NORTH, 0, "ff0101"))
    insert_positions(db_dsns["admin"], departure(SOUTH, 0, "ff0102"))
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    first = run_once(cfg)
    assert q(db_dsns["reader"], "SELECT direction, n_flights FROM operating_directions") == [
        ("unknown", 2)
    ]
    assert {r[5] for r in q(db_dsns["reader"], ASSESSMENTS)} == {"medium"}

    # Nachlieferung im selben Fenster; die ersten Flüge bleiben bestehen (enden vor 14:08).
    insert_positions(db_dsns["admin"], departure(NORTH, 20, "ff0103"))
    add_raw_file(db_dsns["admin"], T0 + timedelta(minutes=20), T0 + timedelta(minutes=30))
    second = run_once(cfg)

    assert second.window_from == T0 + timedelta(minutes=18)
    assert q(db_dsns["reader"], "SELECT direction, n_flights FROM operating_directions") == [
        ("west", 3)
    ]
    rows = q(
        db_dsns["reader"],
        "SELECT f.icao24, f.analysis_run_id, a.run_id, a.confidence FROM flight_assessments a"
        " JOIN flights f ON f.id = a.flight_id ORDER BY 1",
    )
    assert rows == [
        ("ff0101", first.run_id, second.run_id, "high"),
        ("ff0102", first.run_id, second.run_id, "high"),
        ("ff0103", second.run_id, second.run_id, "high"),
    ]


def test_rebuild_reproduces_assessments(db_dsns, cfg):
    scenario(db_dsns["admin"])
    run_once(cfg)
    directions = "SELECT window_start, direction, n_flights, share FROM operating_directions"
    before = q(db_dsns["reader"], ASSESSMENTS), q(db_dsns["reader"], directions)

    result = rebuild(cfg, T0 - timedelta(days=1), T0 + timedelta(days=1))

    assert result.assessments == 5
    assert (q(db_dsns["reader"], ASSESSMENTS), q(db_dsns["reader"], directions)) == before


def test_assessments_follow_flight_deletion(db_dsns, cfg):
    scenario(db_dsns["admin"])
    run_once(cfg)
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        c.execute("DELETE FROM flights")
    assert q(db_dsns["reader"], "SELECT count(*) FROM flight_assessments") == [(0,)]


def test_procedure_must_be_valid_at_flight_date(db_dsns, cfg, tmp_path):
    expired = tmp_path / "procedures.yaml"
    expired.write_text(
        PROCEDURES_FILE.read_text("utf-8").replace("valid_to: null", "valid_to: 2026-11-09"),
        encoding="utf-8",
    )
    sync_procedures(cfg, expired)
    scenario(db_dsns["admin"])
    run_once(cfg)
    assert {(r[4], r[5]) for r in q(db_dsns["reader"], ASSESSMENTS)} == {(None, "none")}


def test_without_procedures_file_step_is_skipped(db_dsns, cfg, caplog):
    scenario(db_dsns["admin"])
    no_file = Config(**{**cfg.__dict__, "procedures_file": None})
    with caplog.at_level("WARNING", logger="analysis"):
        result = run_once(no_file)
    assert (result.flights, result.assessments) == (5, 0)
    assert any("Routenvergleich übersprungen" in r.message for r in caplog.records)
    assert q(db_dsns["reader"], "SELECT count(*) FROM flight_assessments") == [(0,)]


def test_altitude_limit_uses_stored_altitudes(db_dsns, cfg):
    insert_positions(db_dsns["admin"], departure(NORTH, 0, "ff0101"))
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    limited = Config(**{**cfg.__dict__, "route_max_alt_ft": 3000})
    run_once(limited)
    # 500 ft + 2000 ft/min: 3000 ft nach 75 s
    assert q(db_dsns["reader"], "SELECT eval_from, eval_to FROM flight_assessments") == [
        (T0, T0 + timedelta(seconds=75))
    ]
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/db/test_analysis_routes.py -v`
Expected: FAIL mit `ImportError: cannot import name 'sync_procedures'`.

- [ ] **Step 3: `routes.py`** – `analysis/src/analysis/routes.py`:

```python
"""Routenvergleich im Lauf: Rolle je Flug, Betriebsrichtung je Fenster, Bewertung je Flug.

Ablauf: Während der Flugbildung erhält jeder neue Flug mit Rolle eine vorläufige Zeile in
``flight_assessments`` (Bezugszeitpunkt und Stimme). Danach werden die Fenster neu berechnet,
in denen der Lauf Flüge gelöscht oder gebildet hat, und bewertet werden alle neuen Flüge sowie
alle Flüge in Fenstern, deren Betriebsrichtung sich geändert hat.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from analysis import db
from analysis.assign import Reference, assign
from analysis.config import Config
from analysis.deviation import approach, corridor, review, samples, section
from analysis.direction import WINDOW, decide, flight_heading, vote, window_start
from analysis.geo import XY, Local
from analysis.role import determine_role
from analysis.segment import Point

log = logging.getLogger("analysis")

_WINDOW_SQL = "to_timestamp(floor(extract(epoch FROM a.ref_ts) / 1800) * 1800)"


@dataclass(frozen=True)
class RouteContext:
    local: Local
    references: list[Reference]
    runway_headings: list[float]
    zones: list[tuple[int, XY]]  # (geofence_id, Referenzpunkt)


def enabled(cfg: Config) -> bool:
    return cfg.procedures_file is not None and cfg.procedures_file.is_file()


def load_context(conn: psycopg.Connection, cfg: Config) -> RouteContext:
    local = Local(cfg.ber_lat, cfg.ber_lon)
    references = [
        Reference(
            pid,
            name,
            kind,
            direction,
            sector,
            [local.xy(lat, lon) for lon, lat in geojson["coordinates"]],
            valid_from,
            valid_to,
        )
        for pid, name, kind, direction, sector, valid_from, valid_to, geojson in conn.execute(
            "SELECT id, name, kind, direction, sector, valid_from, valid_to,"
            " ST_AsGeoJSON(geom)::json FROM procedures WHERE superseded_at IS NULL ORDER BY id"
        )
    ]
    headings = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT runway_heading_deg FROM procedures WHERE superseded_at IS NULL"
        )
    ]
    zones = [
        (gid, local.xy(lat, lon))
        for gid, lat, lon in conn.execute(
            "SELECT id, ST_Y(ref_point), ST_X(ref_point) FROM geofences"
            " WHERE valid_to IS NULL ORDER BY id"
        )
    ]
    return RouteContext(local, references, headings, zones)


def record_role(
    conn: psycopg.Connection,
    run_id: int,
    flight_id: int,
    points: list[Point],
    ctx: RouteContext,
    cfg: Config,
) -> bool:
    """Legt für einen neuen Flug mit Rolle die vorläufige Bewertungszeile an."""
    role = determine_role(
        points,
        ctx.local,
        ber_radius_m=cfg.ber_radius_m,
        near_m=cfg.role_near_m,
        max_alt_ft=cfg.role_max_alt_ft,
        vrate_fpm=cfg.vrate_fpm,
    )
    if role is None:
        return False
    heading = flight_heading(role, near_m=cfg.role_near_m, dist_m=cfg.direction_dist_m)
    conn.execute(
        "INSERT INTO flight_assessments (flight_id, run_id, role, ref_ts, ref_heading_deg, vote,"
        " flight_sector, confidence, basis) VALUES (%s, %s, %s, %s, %s, %s, %s, 'none',"
        " 'noch nicht bewertet')",
        (
            flight_id,
            run_id,
            role.role,
            role.ref_ts,
            heading,
            vote(heading, ctx.runway_headings, tol_deg=cfg.direction_tol_deg),
            role.sector,
        ),
    )
    return True


def affected_windows(spans: list[tuple[datetime, datetime]]) -> set[datetime]:
    out: set[datetime] = set()
    for first, last in spans:
        w = window_start(first)
        while w <= last:
            out.add(w)
            w += WINDOW
    return out


def update_directions(
    conn: psycopg.Connection, run_id: int, windows: set[datetime], cfg: Config
) -> list[datetime]:
    """Berechnet die Betriebsrichtung der Fenster neu; liefert die Fenster, deren Richtung
    sich geändert hat."""
    if not windows:
        return []
    votes: dict[datetime, list[str]] = defaultdict(list)
    seen: set[datetime] = set()
    for ts, v in conn.execute(
        "SELECT ref_ts, vote FROM flight_assessments WHERE ref_ts >= %s AND ref_ts < %s",
        (min(windows), max(windows) + WINDOW),
    ):
        w = window_start(ts)
        if w in windows:
            seen.add(w)
            if v is not None:
                votes[w].append(v)
    keys = sorted(windows)
    old = dict(
        conn.execute(
            "DELETE FROM operating_directions WHERE window_start = ANY(%s)"
            " RETURNING window_start, direction",
            (keys,),
        ).fetchall()
    )
    changed = []
    for w in sorted(seen):
        d = decide(
            votes[w], min_flights=cfg.direction_min_flights, min_share=cfg.direction_min_share
        )
        conn.execute(
            "INSERT INTO operating_directions (window_start, direction, n_flights, share,"
            " basis, run_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (w, d.direction, d.n_flights, d.share, d.basis, run_id),
        )
        if old.get(w) != d.direction:
            changed.append(w)
    return changed


def flight_points(conn: psycopg.Connection, flight_id: int) -> list[Point]:
    """Spurpunkte eines gespeicherten Flugs mit Höhe aus ``positions``."""
    alts = {
        ts: (alt, rate)
        for ts, alt, rate in conn.execute(
            "SELECT p.ts, p.alt_baro_ft, p.baro_rate_fpm FROM positions p"
            " JOIN flights f ON p.icao24 = f.icao24 AND p.ts BETWEEN f.first_ts AND f.last_ts"
            " WHERE f.id = %s",
            (flight_id,),
        )
    }
    out = []
    for ts, lat, lon in conn.execute(
        "SELECT to_timestamp(ST_M(d.geom)), ST_Y(d.geom), ST_X(d.geom)"
        " FROM flights f, LATERAL ST_DumpPoints(f.track) d WHERE f.id = %s ORDER BY d.path",
        (flight_id,),
    ):
        alt, rate = alts.get(ts, (None, None))
        out.append(Point(ts, lat, lon, alt, rate, None, False))
    return out


def assess(
    conn: psycopg.Connection, run_id: int, flight_id: int, ctx: RouteContext, cfg: Config
) -> None:
    role, sector, direction = conn.execute(
        f"SELECT a.role, a.flight_sector, coalesce(o.direction, 'unknown')"
        f" FROM flight_assessments a"
        f" LEFT JOIN operating_directions o ON o.window_start = {_WINDOW_SQL}"
        f" WHERE a.flight_id = %s",
        (flight_id,),
    ).fetchone()
    points = flight_points(conn, flight_id)
    day = points[0].ts.astimezone(UTC).date()
    track = samples(points, ctx.local)
    a = assign(
        role,
        direction,
        sector,
        track,
        [r for r in ctx.references if r.valid_on(day)],
        max_alt_ft=cfg.route_max_alt_ft,
        ratio=cfg.assign_ratio,
    )
    row = {
        "flight_id": flight_id,
        "run_id": run_id,
        "direction": direction,
        "procedure_id": None if a.reference is None else a.reference.id,
        "confidence": a.confidence,
        "basis": a.basis,
        "mean_dev_m": a.mean_dev_m,
        "second_mean_dev_m": a.second_mean_dev_m,
        "eval_from": None,
        "eval_to": None,
        "max_dev_m": None,
        "outside_s": None,
        "outside_m": None,
        "deviation": False,
        "ref_geofence_id": None,
        "min_dist_ref_m": None,
        "proc_dist_ref_m": None,
        "approach": False,
        "review": False,
        "review_reasons": [],
        "in_reception_gap": None,
        "max_position_gap_s": None,
    }
    if a.confidence in ("high", "medium"):
        sec = section(track, a.reference.line, cfg.route_max_alt_ft)
        c = corridor(sec, half_width_m=cfg.corridor_m, min_s=cfg.corridor_min_s)
        b = approach([s.xy for s, _ in sec], a.reference.line, ctx.zones, tol_m=cfg.approach_tol)
        gap = db.in_reception_gap(conn, c.eval_from, c.eval_to)
        relevant = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM overflight_events WHERE flight_id = %s AND relevant)",
            (flight_id,),
        ).fetchone()[0]
        flagged, reasons = review(
            deviation=c.deviation,
            approach=b.approach,
            confidence=a.confidence,
            in_reception_gap=gap,
            max_position_gap_s=c.max_position_gap_s,
            max_gap_s=cfg.review_max_gap_s,
            relevant_event=relevant,
        )
        row |= {
            "eval_from": c.eval_from,
            "eval_to": c.eval_to,
            "max_dev_m": c.max_dev_m,
            "outside_s": c.outside_s,
            "outside_m": c.outside_m,
            "deviation": c.deviation,
            "ref_geofence_id": b.geofence_id,
            "min_dist_ref_m": b.min_dist_ref_m,
            "proc_dist_ref_m": b.proc_dist_ref_m,
            "approach": b.approach,
            "review": flagged,
            "review_reasons": reasons,
            "in_reception_gap": gap,
            "max_position_gap_s": c.max_position_gap_s,
        }
    sets = ", ".join(f"{k} = %({k})s" for k in row if k != "flight_id")
    conn.execute(f"UPDATE flight_assessments SET {sets} WHERE flight_id = %(flight_id)s", row)


def pending(conn: psycopg.Connection, run_id: int, changed: list[datetime]) -> list[int]:
    """Neue Flüge dieses Laufs und Flüge in Fenstern mit geänderter Betriebsrichtung."""
    return [
        r[0]
        for r in conn.execute(
            f"SELECT a.flight_id FROM flight_assessments a"
            f" WHERE a.run_id = %s OR {_WINDOW_SQL} = ANY(%s) ORDER BY a.flight_id",
            (run_id, changed),
        )
    ]


def run_step(
    conn: psycopg.Connection,
    cfg: Config,
    run_id: int,
    ctx: RouteContext,
    spans: list[tuple[datetime, datetime]],
    counts: db.Counts,
) -> None:
    changed = update_directions(conn, run_id, affected_windows(spans), cfg)
    for flight_id in pending(conn, run_id, changed):
        try:
            with conn.transaction():
                assess(conn, run_id, flight_id, ctx, cfg)
        except psycopg.OperationalError:
            raise
        except Exception as e:
            counts.skipped += 1
            log.warning(
                "Bewertung übersprungen",
                extra={"flight_id": flight_id, "error": str(e)},
                exc_info=True,
            )
            continue
        counts.assessments += 1
```

- [ ] **Step 4: Einbindung**

`analysis/src/analysis/__init__.py`: `__version__ = "0.3.0"`.

`analysis/src/analysis/db.py`, Klasse `Counts`: nach `skipped: int = 0` die Zeile `    assessments: int = 0` ergänzen.

`analysis/src/analysis/pipeline.py` ersetzen durch:

```python
"""Laufsteuerung: Zeitfenster bestimmen, Flüge und Überflüge neu bilden, protokollieren."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

from analysis import __version__, db, events, routes
from analysis.config import Config
from analysis.procedures import ProcedureSync, load_procedures, read_procedures
from analysis.segment import Point, segment
from analysis.zones import ZoneSync, load_zones, read_zones

log = logging.getLogger("analysis")


class SchemaMissing(RuntimeError):
    pass


class NoZones(RuntimeError):
    pass


@dataclass(frozen=True)
class RunResult:
    run_id: int
    kind: str
    window_from: datetime
    window_to: datetime
    flights: int
    events: int
    skipped: int
    assessments: int = 0


def compute_window(conn: psycopg.Connection, cfg: Config) -> tuple[datetime, datetime] | None:
    end = db.data_end(conn)
    if end is None:
        return None
    settle = timedelta(seconds=cfg.settle_s)
    window_to = end - settle
    pending = db.pending_files(conn)
    if pending:
        first = min(pending, key=lambda f: f.start)
        if first.start - settle < window_to:
            window_to = first.start - settle
            # Bleibt eine Datei dauerhaft uneingelesen (z. B. ``failed``), steht die Auswertung.
            log.warning(
                "noch nicht eingelesene Datei begrenzt das Auswertungsfenster",
                extra={
                    "path": first.path,
                    "status": first.status,
                    "file_start": first.start,
                    "waiting_s": round(first.waiting_s),
                },
            )

    last = db.last_incremental(conn)
    if last is None:
        window_from = db.first_position_ts(conn)
        if window_from is None:
            return None
    else:
        window_from, last_started = last
        late = db.late_start(conn, last_started, window_from)
        if late is not None:
            window_from = min(window_from, late - settle)
    if window_to <= window_from:
        return None
    return window_from, window_to


def watermark_lag_s(conn: psycopg.Connection) -> float | None:
    """Abstand zwischen Ende der eingelesenen Daten und dem Wasserzeichen in Sekunden.

    Ohne eingelesene Daten ``None``; ohne erfolgreichen Lauf zählt der Datenbeginn als
    Wasserzeichen. Ein abgeschalteter Empfänger erhöht den Wert nicht."""
    end = db.data_end(conn)
    if end is None:
        return None
    last = db.last_incremental(conn)
    mark = last[0] if last is not None else db.first_data_start(conn)
    return max(0.0, (end - mark).total_seconds())


def _aircraft(
    conn: psycopg.Connection,
    cfg: Config,
    run_id: int,
    icao: str,
    points: list[Point],
    zones: dict[int, int],
    ctx: routes.RouteContext | None,
) -> tuple[int, int, list[tuple[datetime, datetime]]]:
    n_flights = n_events = 0
    spans = []
    for seg in segment(icao, points, gap_s=cfg.flight_gap_s, max_speed_kt=cfg.max_speed_kt):
        flight_id = db.insert_flight(conn, run_id, seg)
        n_flights += 1
        spans.append((seg.first_ts, seg.last_ts))
        for c in events.crossings(conn, flight_id):
            event = events.build_event(c, seg.points, zones[c.geofence_id], cfg)
            event["in_reception_gap"] = db.in_reception_gap(conn, c.entry, c.exit)
            db.insert_event(conn, run_id, flight_id, event)
            n_events += 1
        if ctx is not None:
            routes.record_role(conn, run_id, flight_id, seg.points, ctx, cfg)
    return n_flights, n_events, spans


def _process(
    conn: psycopg.Connection,
    cfg: Config,
    run_id: int,
    start: datetime,
    end: datetime,
    deleted: dict[str, tuple[datetime, datetime]],
) -> db.Counts:
    zones = db.current_zones(conn)
    if not zones:
        raise NoZones("keine aktuelle Zone in geofences – Zonendatei laden")
    if routes.enabled(cfg):
        ctx = routes.load_context(conn, cfg)
    else:
        ctx = None
        log.warning(
            "keine Verfahrensdatei – Routenvergleich übersprungen",
            extra={"file": None if cfg.procedures_file is None else str(cfg.procedures_file)},
        )
    # Gelöschte Flüge werden ab ihrem Beginn neu gebildet, aber nur für ihr Flugzeug.
    ranges = {icao: (min(start, first), max(end, last)) for icao, (first, last) in deleted.items()}
    counts = db.Counts()
    spans = list(deleted.values())
    for icao, points in db.aircraft_points(conn, start, end, ranges):
        try:
            with conn.transaction():
                n_flights, n_events, new = _aircraft(conn, cfg, run_id, icao, points, zones, ctx)
        except psycopg.OperationalError:
            raise
        except Exception as e:
            counts.skipped += 1
            log.warning(
                "Flugzeug übersprungen", extra={"icao24": icao, "error": str(e)}, exc_info=True
            )
            continue
        counts.flights += n_flights
        counts.events += n_events
        spans += new
    if ctx is not None:
        routes.run_step(conn, cfg, run_id, ctx, spans, counts)
    return counts


def _run(
    conn: psycopg.Connection, cfg: Config, kind: str, start: datetime, end: datetime
) -> RunResult:
    gap = timedelta(seconds=cfg.flight_gap_s)
    run_id = db.start_run(conn, kind, __version__, cfg.params(), start, end)
    try:
        with conn.transaction():
            if kind == "incremental":
                deleted = db.delete_flights(conn, last_from=start - gap)
            else:
                deleted = db.delete_flights(conn, last_from=start - gap, first_to=end + gap)
            counts = _process(conn, cfg, run_id, start, end, deleted)
            db.finish_run(conn, run_id, "ok", counts)
    except Exception as e:
        try:
            db.finish_run(conn, run_id, "failed", db.Counts(), str(e))
        except psycopg.Error:
            log.exception("Fehlerstatus nicht gespeichert")
        raise
    return RunResult(
        run_id,
        kind,
        start,
        end,
        counts.flights,
        counts.events,
        counts.skipped,
        counts.assessments,
    )


def _locked(cfg: Config, work):
    with psycopg.connect(cfg.db_dsn, autocommit=True) as conn:
        if not db.schema_ready(conn):
            raise SchemaMissing("Tabelle analysis_runs fehlt – ingest hat noch nicht migriert")
        if not db.try_lock(conn):
            log.info("anderer Lauf aktiv, übersprungen")
            return None
        try:
            return work(conn)
        finally:
            db.unlock(conn)


def run_once(cfg: Config) -> RunResult | None:
    def work(conn):
        window = compute_window(conn, cfg)
        return None if window is None else _run(conn, cfg, "incremental", *window)

    return _locked(cfg, work)


def rebuild(cfg: Config, start: datetime, end: datetime) -> RunResult | None:
    """Berechnet Flüge im Zeitraum neu, höchstens bis zum letzten inkrementellen Lauf."""

    def work(conn):
        last = db.last_incremental(conn)
        if last is None:
            return None
        to = min(end, last[0])
        return None if to <= start else _run(conn, cfg, "rebuild", start, to)

    return _locked(cfg, work)


def sync_zones(cfg: Config, path: Path) -> ZoneSync:
    zones = read_zones(path, cfg.default_relevance_ft)
    with psycopg.connect(cfg.db_dsn, autocommit=True) as conn:
        if not db.schema_ready(conn):
            raise SchemaMissing("Tabelle geofences fehlt – ingest hat noch nicht migriert")
        result = load_zones(conn, zones)
    if result.changed or result.removed:
        log.info(
            "Zonen geändert – ältere Zeiträume bei Bedarf mit 'analysis rebuild' neu berechnen",
            extra={"changed": result.changed, "removed": result.removed},
        )
    return result


def sync_procedures(cfg: Config, path: Path) -> ProcedureSync:
    procedures = read_procedures(
        path, ber_lat=cfg.ber_lat, ber_lon=cfg.ber_lon, ber_radius_m=cfg.ber_radius_m
    )
    with psycopg.connect(cfg.db_dsn, autocommit=True) as conn:
        if conn.execute("SELECT to_regclass('procedures')").fetchone()[0] is None:
            raise SchemaMissing("Tabelle procedures fehlt – ingest hat noch nicht migriert")
        result = load_procedures(conn, procedures)
    if result.changed or result.removed:
        log.info(
            "Verfahren geändert – ältere Zeiträume bei Bedarf mit 'analysis rebuild' neu"
            " berechnen",
            extra={"changed": result.changed, "removed": result.removed},
        )
    return result
```

- [ ] **Step 5: Tests laufen lassen**

Run: `pytest -v`
Expected: alle PASS (`test_analysis_routes.py`: 7; die M3-Pipelinetests bleiben grün und protokollieren je Lauf die Warnung zur fehlenden Verfahrensdatei).

- [ ] **Step 6: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/ tests/db/test_analysis_routes.py
git commit -m "analysis: Routenvergleich im Lauf, Version 0.3.0"
```

---

### Task 10: Befehl `procedures`, Laufzyklus und Prüfskript

**Files:**
- Modify: `analysis/src/analysis/cli.py`
- Create: `scripts/check_procedures.py`
- Test: `tests/analysis/test_analysis_cli.py`, `tests/analysis/test_check_procedures.py`, `tests/db/test_analysis_routes.py`

**Interfaces:**
- Consumes: `pipeline.sync_procedures` (Task 9), `procedures.read_procedures`, `ProcedureError`, `Procedure` (Task 4)
- Produces:
  - `python -m analysis procedures [datei]` – Rückgabe 0 geladen, 1 ungültig (alte Fassung bleibt), 2 keine Datei angegeben
  - `run`/`once`: gleicht die Verfahrensdatei zu Beginn jedes Laufs ab (nach den Zonen); ungültige Datei → Fehlermeldung im Log, Lauf geht mit der bisherigen Fassung weiter
  - `scripts/check_procedures.py datei [--ber-lat …] [--ber-lon …] [--radius-m …]` – Rückgabe 0/1/2; `check_procedures.main(argv) -> int`, `check_procedures.line(p: Procedure) -> str`

Das Prüfskript braucht den Referenzpunkt für die 200-km-Prüfung und den Sektor; Standard sind `ANALYSIS_BER_LAT`/`ANALYSIS_BER_LON`/`ANALYSIS_BER_RADIUS_M` aus der Umgebung. Es gibt je Verfahren Name, Art, Startbahn, Richtung, Sektor, Gültigkeit und Länge aus, keine Koordinaten.

- [ ] **Step 1: Tests schreiben**

In `tests/analysis/test_analysis_cli.py` in der Fixture `env` nach `monkeypatch.delenv("ANALYSIS_ZONES_FILE", raising=False)` ergänzen:

```python
    monkeypatch.delenv("ANALYSIS_PROCEDURES_FILE", raising=False)
```

und am Dateiende anhängen:

```python
def test_procedures_without_file_is_error(env):
    assert cli.main(["procedures"]) == 2


def test_invalid_procedures_file_fails_before_database(env, tmp_path):
    bad = tmp_path / "procedures.yaml"
    bad.write_text("waypoints: []\n", encoding="utf-8")
    assert cli.main(["procedures", str(bad)]) == 1
```

`tests/analysis/test_check_procedures.py`:

```python
from pathlib import Path

import check_procedures

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config" / "procedures.example.yaml"
BER = ["--ber-lat", "45.0", "--ber-lon", "-30.0"]


def test_lists_procedures_without_coordinates(capsys):
    assert check_procedures.main([str(EXAMPLE), *BER]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[1].split() == [
        "ABCDE1W",
        "SID",
        "25",
        "west",
        "NW",
        "2026-11-05",
        "–",
        "offen",
        "77.2",
        "km",
    ]
    assert "4 Verfahren geprüft" in out
    for coordinate in ("45 30", "030 30", "-29.9", "45.4"):
        assert coordinate not in out


def test_invalid_file(tmp_path, capsys):
    bad = tmp_path / "procedures.yaml"
    bad.write_text(EXAMPLE.read_text("utf-8").replace("route: [KLMNO, ABCDE]", "route: []"))
    assert check_procedures.main([str(bad), *BER]) == 1
    assert "ABCDE1W, Feld route" in capsys.readouterr().err


def test_reference_point_required(monkeypatch, capsys):
    monkeypatch.delenv("ANALYSIS_BER_LAT", raising=False)
    monkeypatch.delenv("ANALYSIS_BER_LON", raising=False)
    assert check_procedures.main([str(EXAMPLE)]) == 2
```

Am Ende von `tests/db/test_analysis_routes.py` anhängen:

```python
def test_invalid_file_keeps_previous_version(db_dsns, cfg, tmp_path, monkeypatch):
    from analysis import cli

    bad = tmp_path / "procedures.yaml"
    bad.write_text(PROCEDURES_FILE.read_text("utf-8").replace("route: [TWEST,", "route: [XXXXX,"))
    for k, v in {
        "ANALYSIS_DB_DSN": db_dsns["analysis"],
        "ANALYSIS_BER_LAT": "50",
        "ANALYSIS_BER_LON": "10",
    }.items():
        monkeypatch.setenv(k, v)

    assert cli.main(["procedures", str(bad)]) == 1
    assert q(db_dsns["reader"], "SELECT count(*) FROM procedures WHERE superseded_at IS NULL") == [
        (8,)
    ]
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_analysis_cli.py tests/analysis/test_check_procedures.py tests/db/test_analysis_routes.py -v`
Expected: FAIL (argparse `invalid choice: 'procedures'` mit `SystemExit: 2`, `ModuleNotFoundError: No module named 'check_procedures'`).

- [ ] **Step 3: Implementierung**

`analysis/src/analysis/cli.py` ersetzen durch:

```python
"""Kommandozeile: ``python -m analysis {run|once|rebuild|zones|procedures|health}``."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from analysis import __version__
from analysis.config import Config
from analysis.logjson import setup_logging
from analysis.pipeline import rebuild, run_once, sync_procedures, sync_zones, watermark_lag_s
from analysis.procedures import ProcedureError

log = logging.getLogger("analysis")


def _date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _health() -> int:
    cfg = Config.from_env()
    try:
        age = time.time() - cfg.heartbeat_file.stat().st_mtime
    except FileNotFoundError:
        return 1
    if age > 3 * cfg.interval_s:
        return 1
    try:
        with psycopg.connect(cfg.db_dsn, connect_timeout=5) as c:
            row = c.execute("SELECT status FROM analysis_runs ORDER BY id DESC LIMIT 1").fetchone()
            lag = watermark_lag_s(c)
    except psycopg.Error:
        return 1
    if row and row[0] == "failed":
        return 1
    # Wasserzeichen hängt hinter vorhandenen Daten zurück (z. B. dauerhaft defekte Datei).
    return 1 if lag is not None and lag > cfg.max_lag_s else 0


def _log_result(result) -> None:
    if result is not None:
        log.info(
            "Lauf beendet",
            extra={
                "kind": result.kind,
                "window_from": result.window_from,
                "window_to": result.window_to,
                "flights": result.flights,
                "events": result.events,
                "skipped": result.skipped,
                "assessments": result.assessments,
            },
        )


def _iteration(cfg: Config) -> None:
    if cfg.zones_file is not None:
        sync_zones(cfg, cfg.zones_file)
    if cfg.procedures_file is not None and cfg.procedures_file.is_file():
        try:
            sync_procedures(cfg, cfg.procedures_file)
        except ProcedureError as e:
            log.error(
                "Verfahrensdatei ungültig – bisherige Fassung bleibt aktiv",
                extra={"error": str(e)},
            )
    _log_result(run_once(cfg))
    cfg.heartbeat_file.touch()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analysis")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Dauerbetrieb")
    sub.add_parser("once", help="ein Lauf")
    sub.add_parser("health", help="Healthcheck")
    zp = sub.add_parser("zones", help="Zonendatei laden")
    zp.add_argument("file", nargs="?")
    pp = sub.add_parser("procedures", help="Verfahrensdatei laden")
    pp.add_argument("file", nargs="?")
    rb = sub.add_parser("rebuild", help="Zeitraum neu berechnen")
    rb.add_argument("--from", dest="start", type=_date, required=True)
    rb.add_argument("--to", dest="end", type=_date, required=True)
    args = parser.parse_args(argv)

    if args.cmd == "health":
        return _health()

    setup_logging()
    cfg = Config.from_env()
    if args.cmd == "zones":
        path = Path(args.file) if args.file else cfg.zones_file
        if path is None:
            log.error("keine Zonendatei angegeben (Argument oder ANALYSIS_ZONES_FILE)")
            return 2
        result = sync_zones(cfg, path)
        log.info("Zonen geladen", extra={"changed": result.changed, "removed": result.removed})
        return 0
    if args.cmd == "procedures":
        path = Path(args.file) if args.file else cfg.procedures_file
        if path is None:
            log.error("keine Verfahrensdatei angegeben (Argument oder ANALYSIS_PROCEDURES_FILE)")
            return 2
        try:
            result = sync_procedures(cfg, path)
        except ProcedureError as e:
            log.error("Verfahrensdatei ungültig", extra={"error": str(e)})
            return 1
        log.info("Verfahren geladen", extra={"changed": result.changed, "removed": result.removed})
        return 0
    if args.cmd == "once":
        _iteration(cfg)
        return 0
    if args.cmd == "rebuild":
        result = rebuild(cfg, args.start, args.end)
        _log_result(result)
        return 0 if result is not None else 1

    log.info("analysis gestartet", extra={"version": __version__, "interval_s": cfg.interval_s})
    while True:
        try:
            _iteration(cfg)
        except Exception:
            log.exception("Lauf fehlgeschlagen")
        time.sleep(cfg.interval_s)


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/check_procedures.py`:

```python
#!/usr/bin/env python3
"""Prüft eine Verfahrensdatei offline und listet die Verfahren ohne Koordinaten.

Aufruf: python scripts/check_procedures.py config/local/procedures.yaml
Referenzpunkt aus --ber-lat/--ber-lon oder ANALYSIS_BER_LAT/ANALYSIS_BER_LON, Radius für den
Sektor aus --radius-m oder ANALYSIS_BER_RADIUS_M (Standard 40000).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis" / "src"))

from analysis.procedures import Procedure, ProcedureError, read_procedures  # noqa: E402

HEADER = (
    f"{'Name':<10} {'Art':<4} {'Bahn':<4} {'Richtung':<8} {'Sektor':<6} {'Gültigkeit':<23} Länge"
)


def line(p: Procedure) -> str:
    validity = f"{p.valid_from} – {p.valid_to or 'offen'}"
    return (
        f"{p.name:<10} {p.kind:<4} {p.runway:<4} {p.direction:<8} {p.sector:<6} {validity:<23}"
        f" {p.length_m / 1000:.1f} km"
    )


def _env_float(name: str, default: float | None = None) -> float | None:
    value = os.environ.get(name)
    return float(value) if value else default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--ber-lat", type=float, default=_env_float("ANALYSIS_BER_LAT"))
    parser.add_argument("--ber-lon", type=float, default=_env_float("ANALYSIS_BER_LON"))
    parser.add_argument(
        "--radius-m", type=float, default=_env_float("ANALYSIS_BER_RADIUS_M", 40000.0)
    )
    args = parser.parse_args(argv)
    if args.ber_lat is None or args.ber_lon is None:
        print(
            "Referenzpunkt fehlt: --ber-lat/--ber-lon oder ANALYSIS_BER_LAT/_LON", file=sys.stderr
        )
        return 2
    try:
        procedures = read_procedures(
            args.file, ber_lat=args.ber_lat, ber_lon=args.ber_lon, ber_radius_m=args.radius_m
        )
    except ProcedureError as e:
        print(f"ungültig: {e}", file=sys.stderr)
        return 1
    print(HEADER)
    for p in procedures:
        print(line(p))
    print(f"{len(procedures)} Verfahren geprüft")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest -v && python scripts/check_procedures.py config/procedures.example.yaml --ber-lat 45.0 --ber-lon -30.0`
Expected: alle PASS; Ausgabe:

```text
Name       Art  Bahn Richtung Sektor Gültigkeit              Länge
ABCDE1W    SID  25   west     NW     2026-11-05 – offen      77.2 km
FGHIJ1W    STAR 25   west     N      2026-11-05 – offen      46.0 km
FGHIJ1E    SID  07   east     N      2026-11-05 – offen      64.3 km
ABCDE1E    STAR 07   east     NW     2026-11-05 – offen      58.9 km
4 Verfahren geprüft
```

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/cli.py scripts/check_procedures.py tests/analysis/test_analysis_cli.py tests/analysis/test_check_procedures.py tests/db/test_analysis_routes.py
git commit -m "analysis: Befehl procedures und Prüfskript für die Verfahrensdatei"
```

---

### Task 11: Grafana – Dashboard „Flugrouten“ und Ergänzung „Flugspur“

**Files:**
- Modify: `dashboard/build_dashboards.py`, `tests/fixtures/dashboard_sql.py`, `tests/analysis/test_dashboards.py`, `tests/db/test_analysis_routes.py`
- Create: `dashboard/dashboards/flugrouten.json` (generiert); Modify: `dashboard/dashboards/flugspur.json` (generiert)

**Interfaces:**
- Consumes: Tabellen aus Task 1, Bewertungen aus Task 9; Bausteine `panel`, `stat`, `target`, `query_var`, `custom_var`, `textbox_var`, `dashboard` (M3)
- Produces:
  - `build_dashboards.flugrouten() -> dict` (UID `flightdb-flugrouten`), `build()` mit vier Dashboards
  - Hilfen `markers(name, ref, color, size=2) -> dict`, `geomap(title, grid, targets, layers, padding=5) -> dict`, Konstanten `ROUTE_FILTER`, `CORRIDOR_M`, `FLIGHT`
  - Variablen `procedure` (Mehrfachauswahl, Namen nicht abgelöster Verfahren), `confidence` (`ab mittel`/`nur hoch`/`alle`), `only_review` (`nein`/`ja`)

Layout („Kennzahlen zuerst“, siehe `docs/img/m4-dashboard-flugrouten-mockup.png`): Zeitraum über die Zeitauswahl; Zeile 1 vier Kennzahlen (Bewertbar % – Anteil `high`/`medium` an allen An- und Abflügen im Zeitraum, unabhängig von den Filtern; Abweichungen C; Annäherungen B; Prüffälle E); Zeile 2 Zustandsband Betriebsrichtung (west blau, Ost orange, unbekannt grau) volle Breite; Zeile 3 links Tabelle je Verfahren (Flüge, Anteil Abweichung, Median und 95-%-Wert `max_dev_m`), rechts Karte mit Ideallinien, Korridor und Spuren (Ansicht `fit`); Zeile 4 Tabelle „Prüffälle“ (Zeit, Rufzeichen, Verfahren, Sicherheit, max. Abw., außerhalb, Gründe, Link „Flugspur“).

Grafana-Geomap kann aus SQL keine Flächen zeichnen; der Korridor (`ST_Buffer` auf `geography` mit der halben Breite des letzten erfolgreichen Laufs aus `analysis_runs.params`) erscheint als Randlinie aus Punkten alle 200 m. Ideallinien werden ebenso verdichtet; Spuren zeigen jede fünfte Position der letzten 100 Flüge je Schicht.

- [ ] **Step 1: Tests anpassen**

In `tests/fixtures/dashboard_sql.py` die Liste `VARIABLES` um drei Einträge ergänzen (nach `'\$bucket'`):

```python
    (r"\(\$procedure\)", "('WNORD1W', 'ONORD1W')"),
    (r"'\$confidence'", "'alle'"),
    (r"'\$only_review'", "'nein'"),
```

In `tests/analysis/test_dashboards.py` in `test_dashboards_have_unique_uids_and_panel_ids` `== 3` durch `== 4` ersetzen.

Am Ende von `tests/db/test_analysis_routes.py` anhängen (Inhalte mit Daten statt nur Ausführbarkeit):

```python
def test_dashboard_queries_show_review(db_dsns, cfg):
    import build_dashboards
    from dashboard_sql import substitute

    scenario(db_dsns["admin"])
    run_once(cfg)
    panels = {p["title"]: p for p in build_dashboards.flugrouten()["panels"]}
    with psycopg.connect(db_dsns["reader"]) as c:

        def rows(title, ref=0):
            return c.execute(substitute(panels[title]["targets"][ref]["rawSql"])).fetchall()

        assert rows("Prüffälle (E)") == [(1,)]
        assert rows("Bewertbar (Sicherheit ≥ mittel)") == [(100,)]
        (review,) = rows("Prüffälle")
        assert review[1:4] == ("TST104", "SID WNORD1W", "high")
        assert review[6] == "Abweichung, Annäherung"
        assert rows("Je Verfahren")[0][:3] == ("SID WNORD1W", 3, 33)
        assert len(rows("Ideallinien, Korridor, Spuren", 1)) > 100  # Korridorrand
        spur = {p["title"]: p for p in build_dashboards.flugspur()["panels"]}["Spur"]
        flight_id = str(review[8])
        ideal = c.execute(substitute(spur["targets"][1]["rawSql"], flight_id=flight_id))
        assert len(ideal.fetchall()) > 100
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_dashboards.py tests/db/test_analysis_routes.py -v`
Expected: FAIL (`assert 3 == 4`, `AttributeError: module 'build_dashboards' has no attribute 'flugrouten'`).

- [ ] **Step 3: Generator erweitern** – in `dashboard/build_dashboards.py` alles ab der Zeile `# --- Dashboard „Flugspur“ ---…` bis zum Dateiende ersetzen durch:

```python
# --- Dashboard „Flugrouten“ -------------------------------------------------------------

# Bewertungen mit zugeordnetem Verfahren (Alias a, p) nach den Variablen des Dashboards.
ROUTE_FILTER = """
  $__timeFilter(a.ref_ts)
  AND p.name IN ($procedure)
  AND (a.confidence = 'high'
       OR (a.confidence = 'medium' AND '$confidence' <> 'nur hoch')
       OR '$confidence' = 'alle')
  AND (a.review OR '$only_review' = 'nein')"""

# Halbe Korridorbreite des letzten erfolgreichen Laufs (Standard 1852 m).
CORRIDOR_M = """coalesce((SELECT (params->>'corridor_m')::float8 FROM analysis_runs
    WHERE status = 'ok' ORDER BY id DESC LIMIT 1), 1852)"""

DIRECTION_COLORS = {
    "west": {"color": "blue", "index": 0, "text": "West"},
    "east": {"color": "orange", "index": 1, "text": "Ost"},
    "unknown": {"color": "#808080", "index": 2, "text": "unbekannt"},
}


def markers(name: str, ref: str, color: str, size: int = 2) -> dict:
    return {
        "type": "markers",
        "name": name,
        "filterData": {"id": "byRefId", "options": ref},
        "location": {"mode": "coords", "latitude": "latitude", "longitude": "longitude"},
        "config": {"style": {"size": {"fixed": size}, "color": {"fixed": color}}},
    }


def geomap(title: str, grid, targets: list[dict], layers: list[dict], padding: int = 5) -> dict:
    return panel(
        "geomap",
        title,
        grid,
        targets,
        options={
            "view": {"id": "fit", "allLayers": True, "padding": padding},
            "controls": {"showZoom": True, "mouseWheelZoom": True},
            "basemap": {"type": "default", "name": "Karte"},
            "layers": layers,
        },
    )


def _route_count(condition: str) -> str:
    return f"""
SELECT count(*) AS n
FROM flight_assessments a JOIN procedures p ON p.id = a.procedure_id
WHERE {ROUTE_FILTER}
  AND {condition}"""


def flugrouten() -> dict:
    rated = """
SELECT 100.0 * count(*) FILTER (WHERE a.confidence IN ('high', 'medium'))
  / nullif(count(*), 0) AS "%"
FROM flight_assessments a WHERE $__timeFilter(a.ref_ts)"""
    directions = """
SELECT window_start AS time, direction AS "Betriebsrichtung"
FROM operating_directions WHERE $__timeFilter(window_start) ORDER BY 1"""
    per_procedure = f"""
SELECT p.kind || ' ' || p.name AS "Verfahren", count(*) AS "Flüge",
  round(100.0 * count(*) FILTER (WHERE a.deviation) / count(*)) AS "Abw. %",
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY a.max_dev_m)) AS "Median m",
  round(percentile_cont(0.95) WITHIN GROUP (ORDER BY a.max_dev_m)) AS "95 % m"
FROM flight_assessments a JOIN procedures p ON p.id = a.procedure_id
WHERE {ROUTE_FILTER}
GROUP BY p.kind, p.name ORDER BY count(*) DESC"""
    valid = """p.superseded_at IS NULL AND p.name IN ($procedure)
  AND p.valid_from <= ($__timeTo())::timestamptz::date
  AND (p.valid_to IS NULL OR p.valid_to > ($__timeFrom())::timestamptz::date)"""
    ideal = f"""
SELECT p.name AS procedure, ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM procedures p,
  LATERAL ST_DumpPoints(ST_Segmentize(p.geom::geography, 200)::geometry) d
WHERE {valid}"""
    corridor = f"""
SELECT p.name AS procedure, ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM procedures p,
  LATERAL ST_DumpPoints(ST_Segmentize(ST_ExteriorRing(
    ST_Buffer(p.geom::geography, {CORRIDOR_M})::geometry)::geography, 200)::geometry) d
WHERE {valid}"""

    def tracks(review: bool) -> str:
        return f"""
WITH sel AS (
  SELECT a.flight_id FROM flight_assessments a JOIN procedures p ON p.id = a.procedure_id
  WHERE {ROUTE_FILTER} AND a.review = {str(review).lower()}
  ORDER BY a.ref_ts DESC LIMIT 100
)
SELECT f.id AS flight_id, ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM flights f JOIN sel ON sel.flight_id = f.id, LATERAL ST_DumpPoints(f.track) d
WHERE d.path[1] % 5 = 1"""

    reviews = f"""
SELECT a.ref_ts AS "Zeit", f.callsign AS "Rufzeichen", p.kind || ' ' || p.name AS "Verfahren",
  a.confidence AS "Sicherheit", round(a.max_dev_m) AS "max. Abw. m",
  round(a.outside_s) AS "außerhalb s",
  concat_ws(', ', CASE WHEN a.deviation THEN 'Abweichung' END,
    CASE WHEN a.approach THEN 'Annäherung' END) AS "Gründe",
  'Flugspur' AS "Flugspur", a.flight_id,
  (extract(epoch FROM f.first_ts) * 1000)::bigint AS t_from,
  (extract(epoch FROM f.last_ts) * 1000)::bigint AS t_to
FROM flight_assessments a
JOIN flights f ON f.id = a.flight_id
JOIN procedures p ON p.id = a.procedure_id
WHERE {ROUTE_FILTER} AND a.review
ORDER BY a.ref_ts DESC LIMIT 200"""

    track_link = {
        "title": "Flugspur",
        "url": "/d/flightdb-flugspur/flugspur?var-flight_id=${__data.fields.flight_id}"
        "&from=${__data.fields.t_from}&to=${__data.fields.t_to}",
    }
    hidden = [
        {
            "matcher": {"id": "byName", "options": n},
            "properties": [{"id": "custom.hidden", "value": True}],
        }
        for n in ("flight_id", "t_from", "t_to")
    ]
    panels = [
        stat("Bewertbar (Sicherheit ≥ mittel)", rated, (0, 0, 6, 4), unit="percent"),
        stat("Abweichungen (C)", _route_count("a.deviation"), (6, 0, 6, 4)),
        stat("Annäherungen (B)", _route_count("a.approach"), (12, 0, 6, 4)),
        stat("Prüffälle (E)", _route_count("a.review"), (18, 0, 6, 4)),
        panel(
            "state-timeline",
            "Betriebsrichtung",
            (0, 4, 24, 5),
            [target(directions)],
            fieldConfig={
                "defaults": {
                    "custom": {"insertNulls": 1800000},
                    "mappings": [{"type": "value", "options": DIRECTION_COLORS}],
                },
                "overrides": [],
            },
            options={"mergeValues": True, "showValue": "never"},
        ),
        panel("table", "Je Verfahren", (0, 9, 12, 12), [target(per_procedure)]),
        geomap(
            "Ideallinien, Korridor, Spuren",
            (12, 9, 12, 12),
            [
                target(ideal, ref="A"),
                target(corridor, ref="B"),
                target(tracks(False), ref="C"),
                target(tracks(True), ref="D"),
            ],
            [
                markers("Korridor", "B", "purple", 1),
                markers("Ideallinie", "A", "blue", 2),
                markers("Spuren", "C", "green", 1),
                markers("Prüffälle", "D", "red", 2),
            ],
        ),
        panel(
            "table",
            "Prüffälle",
            (0, 21, 24, 9),
            [target(reviews)],
            description="Eine Abweichung ist kein Verstoß: Radarführung und Freigaben sind aus"
            " ADS-B nicht erkennbar.",
            fieldConfig={
                "defaults": {},
                "overrides": hidden
                + [
                    {
                        "matcher": {"id": "byName", "options": "Flugspur"},
                        "properties": [{"id": "links", "value": [track_link]}],
                    }
                ],
            },
        ),
    ]
    variables = [
        query_var(
            "procedure",
            "Verfahren",
            "SELECT DISTINCT name FROM procedures WHERE superseded_at IS NULL ORDER BY name",
        ),
        custom_var("confidence", "Sicherheit", ["ab mittel", "nur hoch", "alle"], "ab mittel"),
        custom_var("only_review", "Nur Prüffälle", ["nein", "ja"], "nein"),
    ]
    return dashboard("flightdb-flugrouten", "Flugrouten", panels, variables)


# --- Dashboard „Flugspur“ ---------------------------------------------------------------

FLIGHT = "nullif(${flight_id:sqlstring}, '')::bigint"


def flugspur() -> dict:
    # Flug-ID aus der Textbox nur als SQL-Zeichenkette einsetzen und in bigint wandeln:
    # leere Eingabe ergibt keine Zeilen, beliebiger Text einen Typfehler statt SQL.
    assigned = f"p.id = (SELECT procedure_id FROM flight_assessments WHERE flight_id = {FLIGHT})"
    panels = [
        geomap(
            "Spur",
            (0, 0, 14, 14),
            [
                target(
                    f"""
SELECT ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude,
  to_timestamp(ST_M(d.geom)) AS time
FROM flights f, LATERAL ST_DumpPoints(f.track) d
WHERE f.id = {FLIGHT} ORDER BY d.path""",
                    ref="A",
                ),
                target(
                    f"""
SELECT ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM procedures p,
  LATERAL ST_DumpPoints(ST_Segmentize(p.geom::geography, 200)::geometry) d
WHERE {assigned}""",
                    ref="B",
                ),
                target(
                    f"""
SELECT ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM procedures p,
  LATERAL ST_DumpPoints(ST_Segmentize(ST_ExteriorRing(
    ST_Buffer(p.geom::geography, {CORRIDOR_M})::geometry)::geography, 200)::geometry) d
WHERE {assigned}""",
                    ref="C",
                ),
            ],
            [
                markers("Korridor", "C", "purple", 1),
                markers("Ideallinie", "B", "dark-blue", 2),
                markers("Spur", "A", "blue", 3),
            ],
            padding=10,
        ),
        panel(
            "table",
            "Überflüge dieses Flugs",
            (14, 0, 10, 14),
            [
                target(f"""
SELECT g.name AS "Zone", e.entry_ts AS "Eintritt", e.exit_ts AS "Austritt",
  e.min_alt_ft AS "Höhe ft", round(e.min_dist_m) AS "Abstand m", e.heading_sector AS "Richtung",
  e.category AS "Kategorie", e.category_basis::text AS "Begründung"
FROM overflight_events e JOIN geofences g ON g.id = e.geofence_id
WHERE e.flight_id = {FLIGHT} ORDER BY e.entry_ts""")
            ],
        ),
        panel(
            "timeseries",
            "Höhe und Geschwindigkeit",
            (0, 14, 24, 9),
            [
                target(
                    f"""
SELECT p.ts AS time, p.alt_baro_ft AS "Höhe ft", p.gs_kt AS "Geschwindigkeit kt"
FROM positions p JOIN flights f ON p.icao24 = f.icao24
  AND p.ts BETWEEN f.first_ts AND f.last_ts
WHERE f.id = {FLIGHT} ORDER BY 1""",
                    "time_series",
                )
            ],
        ),
        panel(
            "table",
            "Bewertung (Flugroutenvergleich)",
            (0, 23, 24, 6),
            [
                target(f"""
SELECT a.role AS "Rolle", a.direction AS "Betriebsrichtung", a.flight_sector AS "Sektor",
  p.kind || ' ' || p.name AS "Verfahren", a.confidence AS "Sicherheit",
  round(a.max_dev_m) AS "max. Abw. m", round(a.outside_s) AS "außerhalb s",
  a.deviation AS "Abweichung", a.approach AS "Annäherung", a.review AS "Prüffall",
  array_to_string(a.review_reasons, ', ') AS "erfüllt", a.basis AS "Begründung"
FROM flight_assessments a LEFT JOIN procedures p ON p.id = a.procedure_id
WHERE a.flight_id = {FLIGHT}""")
            ],
        ),
    ]
    variables = [textbox_var("flight_id", "Flug-ID", "0")]
    return dashboard("flightdb-flugspur", "Flugspur", panels, variables, time_from="now-24h")


def build() -> dict[str, dict]:
    return {
        "ueberfluege.json": ueberfluege(),
        "datenqualitaet.json": datenqualitaet(),
        "flugspur.json": flugspur(),
        "flugrouten.json": flugrouten(),
    }


def write(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, d in build().items():
        (out / name).write_text(
            json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    write()
```

- [ ] **Step 4: Erzeugen und prüfen**

Run: `python dashboard/build_dashboards.py && python scripts/check_dashboards.py dashboard/dashboards/*.json && pytest -v`
Expected: Prüfskript ohne Ausgabe, alle Tests PASS (Dashboard-Abfragen laufen als `flightdb_reader`, auch die neuen Flugspur-Abfragen mit leerer und ungültiger Flug-ID).

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add dashboard/ tests/fixtures/dashboard_sql.py tests/analysis/test_dashboards.py tests/db/test_analysis_routes.py
git commit -m "Grafana: Dashboard Flugrouten, Verfahren und Bewertung in Flugspur"
```

---

### Task 12: End-to-End mit An- und Abflügen

**Files:**
- Modify: `tests/fixtures/synthetic/serve.py` (ersetzen), `tests/e2e/compose.yml`, `tests/e2e/test_e2e.py`
- Test: `tests/analysis/test_e2e_flightplan.py`

**Interfaces:**
- Consumes: Container `analysis` (Tasks 2–10), Dashboards (Task 11), `tests/fixtures/procedures.test.yaml` (Task 4)
- Produces: `serve.scripted(elapsed: float) -> list[dict]`, `serve.current_snapshot(t, started=None)`; E2E-Test `test_routes_direction_assignment_and_one_review`

Die readsb-Attrappe fliegt zusätzlich zu den drei kreisenden Flugzeugen (ff0000–ff0002) planmäßig: Abflug ff0110 auf WNORD1W bis WNMID (300 kt, ab 500 ft mit 3000 ft/min, alle 300 s ab 30 s), Anflug ff0111 auf ONORD1W mit Endanflug (250 kt, ab 8000 ft mit −1500 ft/min, alle 360 s ab 60 s) und einmalig ab 150 s den Abflug ff0112 mit Umweg über (−23000, 6000). Das Rufzeichen wechselt je Umlauf (`TST100`, `TST101`, …), damit jeder Umlauf ein eigener Flug ist. Der E2E-Stack setzt den Referenzpunkt auf den Testflughafen (50,0° N / 10,0° O) und `ANALYSIS_BER_RADIUS_M=25000`, damit die Flüge kurz bleiben; bei 25 km liegen die Sektoren von WNORD1W (`NW`, 309,8°) und ONORD1W (`NO`, 50,2°) je gut 17° von der nächsten Sektorgrenze entfernt. Die Testzone (30 km um 50° N / 10° O) liefert jedem Flug einen relevanten Überflug; nur der Umweg weicht ab, daher genau ein Prüffall.

Der neue Offline-Test rechnet die geplanten Flüge mit den Modulen aus Tasks 4–8 nach, bevor der langsame E2E-Test läuft.

- [ ] **Step 1: Offline-Test schreiben** – `tests/analysis/test_e2e_flightplan.py`:

```python
"""Die geplanten Flüge der readsb-Attrappe ergeben die im E2E-Test erwarteten Bewertungen."""

from datetime import UTC, datetime, timedelta

import pytest
from synthetic import serve
from synthetic.routes import LOCAL, PROCEDURES_FILE

from analysis.assign import Reference, assign
from analysis.deviation import corridor, samples, section
from analysis.direction import flight_heading, vote
from analysis.procedures import read_procedures
from analysis.role import determine_role
from analysis.segment import Point

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
RADIUS_M = 25000.0  # wie ANALYSIS_BER_RADIUS_M in tests/e2e/compose.yml


def flight(hex_: str, start_s: int, end_s: int) -> list[Point]:
    out = []
    for s in range(start_s, end_s):
        for p in serve.scripted(float(s)):
            if p["hex"] == hex_:
                ts = T0 + timedelta(seconds=s)
                out.append(
                    Point(ts, p["lat"], p["lon"], p["alt_baro"], p["baro_rate"], p["flight"], False)
                )
    return out


def references() -> list[Reference]:
    procs = read_procedures(PROCEDURES_FILE, ber_lat=50.0, ber_lon=10.0, ber_radius_m=RADIUS_M)
    return [
        Reference(
            i,
            p.name,
            p.kind,
            p.direction,
            p.sector,
            [LOCAL.xy(*c) for c in p.line],
            p.valid_from,
            p.valid_to,
        )
        for i, p in enumerate(procs)
    ]


@pytest.mark.parametrize(
    "hex_, window, role, procedure, deviation",
    [
        ("ff0110", (30, 330), "departure", "WNORD1W", False),
        ("ff0111", (60, 420), "arrival", "ONORD1W", False),
        ("ff0112", (150, 550), "departure", "WNORD1W", True),
    ],
)
def test_scripted_flight(hex_, window, role, procedure, deviation):
    points = flight(hex_, *window)
    r = determine_role(
        points, LOCAL, ber_radius_m=RADIUS_M, near_m=10000, max_alt_ft=3000, vrate_fpm=300
    )
    assert r.role == role
    assert vote(flight_heading(r, near_m=10000, dist_m=15000), [270.0, 90.0], tol_deg=30) == "west"
    track = samples(points, LOCAL)
    a = assign(role, "west", r.sector, track, references(), max_alt_ft=None, ratio=2.0)
    assert (a.reference.name, a.confidence) == (procedure, "high")
    c = corridor(section(track, a.reference.line, None), half_width_m=1852, min_s=30)
    assert c.deviation is deviation


def test_one_flight_per_cycle_and_detour_once():
    calls = {p["flight"] for s in range(0, 1300) for p in serve.scripted(float(s))}
    assert {"TST100", "TST101", "TST102", "TST110", "TST111", "TST120"} <= calls
    assert not any(c.startswith("TST12") and c != "TST120" for c in calls)
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_e2e_flightplan.py -v`
Expected: FAIL mit `AttributeError: module 'synthetic.serve' has no attribute 'scripted'`.

- [ ] **Step 3: Attrappe erweitern** – `tests/fixtures/synthetic/serve.py` ersetzen durch:

```python
"""readsb-Attrappe: liefert /data/aircraft.json mit synthetischen Flugzeugen (ff0xxx).

Drei Flugzeuge kreisen um 50° N / 10° O (ff0000–ff0002). Dazu fliegen Abflüge (ff0110) und
Anflüge (ff0111) im Takt auf erfundenen Verfahren aus ``procedures.test.yaml`` und einmalig ein
Abflug mit Umweg (ff0112). Rufzeichen wechseln je Umlauf, damit jeder Umlauf ein Flug ist.
"""

from __future__ import annotations

import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from synthetic.generator import aircraft, snapshot

CENTER = (50.0, 10.0)
EARTH_RADIUS_M = 6_371_008.8
KT_TO_MS = 1852 / 3600

# Wegpunkte in m (x Ost, y Nord) um CENTER, wie in procedures.test.yaml
DEPARTURE = [(-1500.0, 0.0), (-16000.0, 0.0), (-20000.0, 20000.0)]  # WNORD1W bis WNMID
DETOUR = [(-1500.0, 0.0), (-16000.0, 0.0), (-23000.0, 6000.0), (-20000.0, 20000.0)]
ARRIVAL = [(23000.0, 24000.0), (20000.0, 20000.0), (16000.0, 0.0), (1500.0, 0.0)]  # ONORD1W

# (hex, Route, kt, Starthöhe ft, ft/min, erster Start s, Takt s oder None = einmalig)
SCHEDULE = [
    ("ff0110", DEPARTURE, 300, 500, 3000, 30, 300),
    ("ff0111", ARRIVAL, 250, 8000, -1500, 60, 360),
    ("ff0112", DETOUR, 300, 500, 3000, 150, None),
]


def latlon(x: float, y: float) -> tuple[float, float]:
    """Lokale Ebene → Grad (gleichabständig; im Umkreis 30 km auf < 100 m genau)."""
    lat = CENTER[0] + math.degrees(y / EARTH_RADIUS_M)
    lon = CENTER[1] + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(CENTER[0]))))
    return lat, lon


def along(route: list[tuple[float, float]], dist: float) -> tuple[float, float] | None:
    for a, b in zip(route, route[1:], strict=False):
        leg = math.dist(a, b)
        if dist <= leg:
            f = dist / leg
            return a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
        dist -= leg
    return None


def scripted(elapsed: float) -> list[dict]:
    """Planmäßige An- und Abflüge ``elapsed`` Sekunden nach dem Start der Attrappe."""
    planes = []
    for hex_, route, kt, alt0, vrate, first, period in SCHEDULE:
        if elapsed < first:
            continue
        cycle, t = (0, elapsed - first) if period is None else divmod(elapsed - first, period)
        pos = along(route, t * kt * KT_TO_MS)
        if pos is None:
            continue
        lat, lon = latlon(*pos)
        planes.append(
            aircraft(
                hex=hex_,
                lat=lat,
                lon=lon,
                alt_baro=round(alt0 + vrate * t / 60),
                seen_pos=0.4,
                flight=f"TST{hex_[-2:]}{int(cycle) % 10}",
                gs=float(kt),
                baro_rate=vrate,
            )
        )
    return planes


def current_snapshot(t: float, started: float | None = None) -> dict:
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
    if started is not None:
        planes += scripted(t - started)
    return snapshot(round(t, 1), planes)


class Handler(BaseHTTPRequestHandler):
    started = time.time()

    def do_GET(self):
        if self.path != "/data/aircraft.json":
            self.send_error(404)
            return
        body = json.dumps(current_snapshot(time.time(), self.started)).encode()
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

Run: `pytest tests/analysis/test_e2e_flightplan.py -v`
Expected: 4 PASS.

- [ ] **Step 4: Compose erweitern** – in `tests/e2e/compose.yml` beim Dienst `analysis` die Zeilen ab `      ANALYSIS_BER_LAT: "49.0"` bis zum Ende des Dienstes ersetzen durch:

```yaml
      # Erfundener Flughafen aus tests/fixtures/procedures.test.yaml
      ANALYSIS_BER_LAT: "50.0"
      ANALYSIS_BER_LON: "10.0"
      ANALYSIS_BER_RADIUS_M: "25000"
      ANALYSIS_ZONES_FILE: /zones/zones.example.geojson
      ANALYSIS_PROCEDURES_FILE: /zones/procedures.test.yaml
    volumes:
      - ./zones.example.geojson:/zones/zones.example.geojson:ro
      - ../fixtures/procedures.test.yaml:/zones/procedures.test.yaml:ro
```

- [ ] **Step 5: E2E-Tests anpassen** – in `tests/e2e/test_e2e.py`:

Nach `GRAFANA = "http://localhost:3002"` ergänzen:

```python
CIRCLING = "('ff0000', 'ff0001', 'ff0002')"  # kreisende Flugzeuge der Attrappe
```

In `test_pipeline_end_to_end` die Zeile `assert query("SELECT count(DISTINCT icao24) FROM positions")[0] == 3` ersetzen durch:

```python
    assert query(f"SELECT count(DISTINCT icao24) FROM positions WHERE icao24 IN {CIRCLING}") == (3,)
```

`test_analysis_builds_one_flight_and_event_per_aircraft` ersetzen durch:

```python
def test_analysis_builds_one_flight_and_event_per_aircraft(stack):
    events = (
        "SELECT count(*) FROM overflight_events e JOIN flights f ON f.id = e.flight_id"
        f" WHERE f.icao24 IN {CIRCLING}"
    )
    wait_for(lambda: query(events)[0] >= 3)
    assert query(
        f"SELECT count(*), count(DISTINCT icao24) FROM flights WHERE icao24 IN {CIRCLING}"
    ) == (3, 3)
    assert query(events) == (3,)
    assert query("SELECT count(*) FROM analysis_runs WHERE status = 'failed'") == (0,)
```

In `test_grafana_provisions_dashboards_and_runs_queries` die UID-Prüfung ersetzen durch:

```python
    assert {
        "flightdb-ueberfluege",
        "flightdb-datenqualitaet",
        "flightdb-flugspur",
        "flightdb-flugrouten",
    } <= uids
```

Am Dateiende anhängen (abgeschlossene Flüge: Beginn aufgezeichnet und Ende mindestens 30 s vor dem letzten Fensterende, damit angeschnittene oder noch laufende Flüge nicht zählen):

```python
WINDOW = "to_timestamp(floor(extract(epoch FROM a.ref_ts) / 1800) * 1800)"
# Abgeschlossene Flüge, deren Beginn aufgezeichnet wurde (nicht der erste, angeschnittene).
COMPLETE = """
  f.first_ts > (SELECT min(ts) FROM positions) + interval '5 seconds'
  AND f.last_ts < (SELECT max(window_to) FROM analysis_runs WHERE status = 'ok')
                  - interval '30 seconds'"""


def test_routes_direction_assignment_and_one_review(stack):
    detour = (
        "SELECT count(*) FROM flight_assessments a JOIN flights f ON f.id = a.flight_id"
        f" WHERE f.icao24 = 'ff0112' AND a.review AND {COMPLETE}"
    )
    wait_for(lambda: query(detour)[0] == 1, timeout=600)

    assert query("SELECT count(*) FROM flight_assessments WHERE review") == (1,)
    assert query("SELECT count(*) FROM operating_directions WHERE direction = 'west'")[0] >= 1
    assert query("SELECT count(*) FROM operating_directions WHERE direction = 'east'") == (0,)
    high, other = query(
        "SELECT count(*) FILTER (WHERE a.confidence = 'high'),"
        " count(*) FILTER (WHERE a.confidence <> 'high')"
        " FROM flight_assessments a JOIN flights f ON f.id = a.flight_id"
        f" JOIN operating_directions o ON o.window_start = {WINDOW}"
        f" WHERE o.direction = 'west' AND {COMPLETE}"
    )
    assert high >= 3 and other == 0
    assert query("SELECT count(*) FROM analysis_runs WHERE status = 'failed'") == (0,)
```

- [ ] **Step 6: E2E laufen lassen**

Run: `pytest -m e2e -v`
Expected: 5 PASS (Laufzeit rund 8 Minuten; der Routentest wartet bis zu 600 s, bis der Umweg abgeschlossen, die Betriebsrichtung `west` erkannt und der Flug als Prüffall bewertet ist). Bei Fehlschlag die am Ende ausgegebenen Container-Logs lesen.

- [ ] **Step 7: Lint und Commit**

```bash
ruff format . && ruff check .
git add tests/fixtures/synthetic/serve.py tests/e2e/ tests/analysis/test_e2e_flightplan.py
git commit -m "End-to-End-Test um An- und Abflüge mit Prüffall erweitert"
```

---

### Task 13: Dokumentation

**Files:**
- Create: `docs/routes.md`, `docs/decisions/0007-zuordnung-zu-flugverfahren.md`
- Modify: `docs/decisions/README.md`, `docs/analysis.md`, `docs/data-model.md`, `docs/dashboard.md`, `docs/deployment-nas.md`, `README.md`

- [ ] **Step 1: `docs/routes.md`**

````markdown
# Flugroutenvergleich

Der Dienst `analysis` vergleicht An- und Abflüge mit den veröffentlichten Abflug- und
Anflugverfahren (SID/STAR) von BER. Jeder Flug mit Rolle erhält eine Bewertung in
`flight_assessments` mit Zuordnungssicherheit, Begründung und Datenqualität.

> **Eine Abweichung ist kein Verstoß.** Radarführung und individuelle Freigaben der Flugsicherung
> sind zulässig und aus ADS-B-Daten nicht erkennbar. Eine statistisch typische Spur ist kein
> veröffentlichtes Verfahren. Markierte Flüge sind Fälle zur manuellen Prüfung.

## Verfahrensdatei

Ort: `config/local/procedures.yaml` (gitignored; im NAS-Stack `/zones/procedures.yaml`).
Vorlage mit erfundenem Flughafen im Atlantik: `config/procedures.example.yaml`.

| Abschnitt | Inhalt |
|---|---|
| `source` | Quelle, frei (erscheint in `procedures.source`), z. B. „DFS AIP Germany, AD 2 EDDB, AIRAC 2611“ |
| `waypoints` | Name → Koordinate, `"GG MM SS.ssN GGG MM SS.ssE"` wie in der AIP oder `[lat, lon]` |
| `runways` | Bezeichnung in Anführungszeichen (`"25R"`) → Schwelle; zu jeder Bahn auch die Gegenrichtung |
| `procedures` | je Verfahren `name`, `kind` (`SID`/`STAR`), `runway`, `valid_from`, `valid_to` (`null` = offen), `airac`, `route` (Wegpunktfolge), optional `constraints` (nur Anzeige) |

Geometrie: Eine SID beginnt an der Schwelle der Gegenrichtung (Abflugende der Bahn, für `25R`
die Schwelle `07L`) und führt über die Wegpunkte; eine STAR verbindet nur ihre Wegpunkte, ohne
Endanflug. Die Betriebsrichtung eines Verfahrens folgt aus dem Kurs der Startbahn (Schwelle →
Gegenschwelle): 180–359° `west`, 0–179° `east`. Der Sektor (`N`, `NO`, …) ist die Richtung vom
BER-Referenzpunkt zu dem Punkt, an dem die Linie den BER-Radius verlässt (SID) bzw. betritt
(STAR).

Die Datei wird als Ganzes abgelehnt – die bisherige Fassung bleibt aktiv –, wenn ein Wegpunkt
oder eine Startbahn unbekannt ist, eine Koordinate unlesbar oder außerhalb ±90/±180 liegt, ein
Wegpunkt weiter als 200 km vom Referenzpunkt entfernt ist, ein Name doppelt vorkommt (Verfahren:
bei überlappender Gültigkeit), eine SID keinen bzw. eine STAR weniger als zwei Wegpunkte hat oder
`valid_to` vor `valid_from` liegt. Meldungen nennen Eintrag und Feld, nie Koordinaten.

Ändert sich ein Verfahren (gleicher Name, gleicher `valid_from`), entsteht eine neue Fassung; die
alte erhält `superseded_at`. Verfahren, die aus der Datei entfernt werden, werden ebenso
geschlossen.

## Übertragen aus der AIP

Quelle ist die veröffentlichte AIP Germany der DFS (Teil AD 2, Flugplatz EDDB). Abschnittsnummern
und Kartentitel können sich mit neuen Ausgaben ändern; maßgeblich ist die gültige Ausgabe.

| Angabe in der Datei | Fundstelle (in der Regel) |
|---|---|
| Schwellen (`runways`) | AD 2 EDDB, Abschnitt zu den Start- und Landebahnen (AD 2.12, Spalte mit den Schwellenkoordinaten) |
| Verfahren, Startbahn, Wegpunktfolge | SID- und STAR-Karten von EDDB mit den zugehörigen Streckenbeschreibungen |
| Wegpunktkoordinaten | Wegpunkttabellen auf bzw. zu den Karten; sonst ENR 4.4 (wichtige Punkte) |
| `valid_from`, `airac` | Beginn des AIRAC-Zyklus, ab dem die Seiten gelten |
| `constraints` | Höhen- und Geschwindigkeitsangaben der Karten (nur zur Anzeige) |

Vorgehen:

1. Gültige AIRAC-Ausgabe wählen und `source` mit Ausgabe und Zyklus füllen.
2. Schwellen beider Richtungen und alle benötigten Wegpunkte übertragen; Koordinaten wörtlich
   aus der AIP abschreiben (Grad, Minuten, Sekunden).
3. Je Verfahren die Wegpunktfolge vom ersten Wegpunkt nach dem Abflug bzw. bis zum letzten
   Wegpunkt vor dem Endanflug eintragen.
4. Prüfen: `python scripts/check_procedures.py config/local/procedures.yaml` (Referenzpunkt aus
   `ANALYSIS_BER_LAT`/`ANALYSIS_BER_LON` oder `--ber-lat`/`--ber-lon`). Die Ausgabe nennt je
   Verfahren Art, Bahn, Richtung, Sektor, Gültigkeit und Länge; unplausible Sektoren oder Längen
   deuten auf Übertragungsfehler hin.
5. Optional die Linien lokal in QGIS gegen die Karte prüfen (Datei nicht auf fremde Seiten laden).
6. Laden: `sudo docker compose exec analysis python -m analysis procedures`.

Bei einem AIRAC-Wechsel geänderte Verfahren mit neuem `valid_from` als neuen Eintrag anlegen und
beim bisherigen `valid_to` setzen. Für einen Flug gilt die nicht abgelöste Fassung, deren
Gültigkeit das UTC-Datum des Flugbeginns enthält.

## Methodik

Gerechnet wird in einer lokalen mittabstandstreuen Ebene um den BER-Referenzpunkt; im Umkreis von
100 km ist der Fehler gegenüber der Korridorbreite vernachlässigbar.

### Rolle

Betrachtet wird der Teil der Spur innerhalb von `ANALYSIS_BER_RADIUS_M`. **Abflug:** Der Teil
beginnt näher als `ANALYSIS_ROLE_NEAR_M` (10 km) am Referenzpunkt unterhalb
`ANALYSIS_ROLE_MAX_ALT_FT` (3000 ft) und steigt im Mittel stärker als `ANALYSIS_VRATE_FPM`.
**Anflug:** spiegelbildlich am Ende des Teils mit Sinken. Andere Flüge erhalten keine Bewertung.

### Betriebsrichtung

Bezugskurs eines Flugs ist der Kurs zwischen den Spurpunkten am Rand von 10 km und bei
`ANALYSIS_DIRECTION_DIST_M` (15 km), bei Abflügen am Anfang, bei Anflügen am Ende. Weicht er
höchstens `ANALYSIS_DIRECTION_TOL_DEG` (30°) vom nächsten Startbahnkurs ab, stimmt der Flug für
dessen Richtung. Je 30-Minuten-Fenster (UTC) gilt die Mehrheit, wenn mindestens
`ANALYSIS_DIRECTION_MIN_FLIGHTS` (3) Stimmen vorliegen und ihr Anteil mindestens
`ANALYSIS_DIRECTION_MIN_SHARE` (0,8) beträgt; sonst `unknown`. Kommen Flüge nach, werden die
betroffenen Fenster und die Flüge darin neu bewertet.

### Zuordnung

1. Kandidaten: gültige Verfahren passender Art (SID ↔ Abflug, STAR ↔ Anflug) und – wenn bekannt –
   passender Betriebsrichtung.
2. Sektor: gleicher Sektor „passt genau“, Nachbarsektor „passt ungefähr“, sonst ausgeschlossen.
3. Geometrie: mittlerer seitlicher Abstand der Positionen im Geltungsabschnitt zur Ideallinie;
   das kleinste Mittel gewinnt.
4. Sicherheit: `high`, wenn die Richtung bekannt ist, der Sektor genau passt und das zweitbeste
   Verfahren mindestens `ANALYSIS_ASSIGN_RATIO` (2,0) mal so weit entfernt ist (oder keines in
   Frage kommt); `medium`, wenn genau eine dieser Bedingungen fehlt; `low` bei mehreren; `none`
   ohne Kandidat.

Die Begründung (`basis`) nennt je Prüfung einen Satz.

### Abweichung (C)

Geltungsabschnitt sind die Positionen, deren Lotfußpunkt zwischen Anfang und Ende der Ideallinie
liegt, bei gesetztem `ANALYSIS_ROUTE_MAX_ALT_FT` nur bis zu dieser Höhe. Bewertet wird nur bei
Sicherheit `high` oder `medium`. Der Korridor hat die halbe Breite `ANALYSIS_CORRIDOR_M`
(1852 m = 1 NM). Außerhalb-Abschnitte entstehen aus aufeinanderfolgenden Positionen, Ein- und
Austritt werden linear interpoliert. `deviation` gilt, wenn ein Abschnitt mindestens
`ANALYSIS_CORRIDOR_MIN_S` (30 s) dauert; kurze Überschwinger zählen nur in `outside_s`.

### Annäherung (B)

Für jede aktuelle Zone wird der kleinste Abstand der Spur (im Geltungsabschnitt) und der
Ideallinie zum Zonen-Referenzpunkt bestimmt. Maßgeblich ist die Zone mit der kleinsten Differenz
Spur − Ideallinie. `approach` gilt, wenn die Spur mehr als `ANALYSIS_APPROACH_TOL_M` (Standard
wie der Korridor) näher kommt als die Ideallinie.

### Prüffall (E)

Ein Flug ist Prüffall, wenn alle Bedingungen gelten: Abweichung oder Annäherung; Sicherheit
`high` oder `medium`; keine Empfangslücke im bewerteten Abschnitt und größte Positionslücke
höchstens `ANALYSIS_REVIEW_MAX_GAP_S` (30 s); mindestens ein relevanter Überflug des Flugs.
`review_reasons` listet die erfüllten Bedingungen.

## Grenzen

- Die Ideallinie verbindet Schwelle und Wegpunkte geradlinig. Kurvenradien, Überflug- oder
  Vorbeiflugwegpunkte, Bögen, Warteschleifen sowie Höhen- und Geschwindigkeitsvorgaben sind nicht
  modelliert; eine STAR endet am letzten Wegpunkt vor dem Endanflug.
- Radarführung und Direktfreigaben erscheinen als Abweichung; Kategorie D (auffällige
  Flugführung) folgt später.
- Ohne Empfang nahe BER in geringer Höhe fällt die Rolle aus und es entstehen keine Bewertungen
  (zeigt erst die Abnahme mit Hardware).
- Bei wenig Verkehr (z. B. nachts) bleibt die Betriebsrichtung oft `unknown`; Zuordnungen sind
  dann höchstens `medium`.
- Flüge nahe einer Sektorgrenze können in den Nachbarsektor fallen („passt ungefähr“).
- `rebuild` verwendet die aktuell nicht abgelösten Fassungen der Verfahren.
- Der Wert für `ANALYSIS_ROUTE_MAX_ALT_FT` ist noch aus der AIP bzw. aus Veröffentlichungen zur
  Radarführung abzuleiten; bis dahin wird ohne Höhengrenze verglichen.
- Die Karte im Dashboard zeigt den Korridor als Randlinie.

## Urheberrecht

Inhalte der AIP unterliegen dem Urheberrecht der DFS Deutsche Flugsicherung GmbH. Die
übertragene Datei bleibt lokal in `config/local/` und wird nicht veröffentlicht; das Repository
enthält nur erfundene Beispiele.
````

- [ ] **Step 2: ADR** – `docs/decisions/0007-zuordnung-zu-flugverfahren.md`:

```markdown
# 0007 – Zuordnung zu Flugverfahren in Stufen

**Status:** angenommen

## Kontext

Flugspuren sollen mit veröffentlichten Abflug- und Anflugverfahren verglichen werden. Die
Flugsicherung führt Flüge oft per Radar oder gibt Direktfreigaben; welches Verfahren ein Flug
erhalten hat, ist aus ADS-B nicht erkennbar. Eine reine Suche nach der nächstgelegenen Linie
würde bei parallelen oder sich überlagernden Verfahren und bei wechselnder Betriebsrichtung
falsche, aber scheinbar sichere Zuordnungen liefern.

## Entscheidung

Die Zuordnung erfolgt in Stufen: zuerst Rolle (Abflug/Anflug) und Betriebsrichtung je
30-Minuten-Fenster aus den Kursen aller Flüge, dann Kandidaten nach Art, Richtung und Sektor,
zuletzt die Geometrie (mittlerer seitlicher Abstand zur Ideallinie). Jede Zuordnung erhält eine
Sicherheitsstufe (`high`, `medium`, `low`, `none`) nach der Zahl nicht erfüllter Bedingungen und
eine Begründung je Prüfung. Abweichung, Annäherung und Prüffall werden nur bei `high` oder
`medium` bewertet. Verfahren werden von Hand aus der AIP in eine lokale Datei übertragen und
versioniert gespeichert.

## Konsequenzen

- Jede Bewertung ist nachvollziehbar: Richtung, Sektor und Abstände stehen in der Begründung.
- Unsichere Fälle werden ausgewiesen statt bewertet; der Anteil bewertbarer Flüge ist eine
  eigene Kennzahl.
- Die Methode hängt von der Sicht des Empfängers nahe BER ab und modelliert keine Kurvenradien.
- Neue AIRAC-Zyklen erfordern eine manuelle Pflege der Verfahrensdatei.
```

In `docs/decisions/README.md` die Tabelle ergänzen:

```markdown
| [0007](0007-zuordnung-zu-flugverfahren.md) | Zuordnung zu Flugverfahren in Stufen mit Sicherheitsstufe | angenommen |
```

- [ ] **Step 3: `docs/analysis.md`**

Einleitung ersetzen durch:

```markdown
Dienst `analysis` auf dem NAS (Rolle `flightdb_analysis`). Er liest `positions` und schreibt
`flights`, `overflight_events`, `analysis_runs` sowie für den Flugroutenvergleich `procedures`,
`operating_directions` und `flight_assessments`. Erfassung und Ingest laufen unabhängig davon.
```

Im Abschnitt `## Ablauf eines Laufs` Punkt 1 und 4 ersetzen und Punkt 5 anhängen:

```markdown
1. Zonendatei (`ANALYSIS_ZONES_FILE`) und Verfahrensdatei (`ANALYSIS_PROCEDURES_FILE`) abgleichen:
   geänderte Zonen und Verfahren erhalten eine neue Fassung.
```

```markdown
4. Flugbildung, Zonendurchquerungen, Kennwerte und Einstufung; alles in einer Transaktion.
5. Flugroutenvergleich: Rolle, Betriebsrichtung je 30-Minuten-Fenster, Zuordnung zu einem
   Verfahren und Bewertung (Details: [routes.md](routes.md)).
```

Im Abschnitt `## Fehlerbehandlung und Betrieb` nach dem zweiten Absatz einfügen:

```markdown
Fehlt die Verfahrensdatei, entfällt der Routenvergleich; jeder Lauf protokolliert eine Warnung,
`health` bleibt grün. Ist sie ungültig, bleibt die bisherige Fassung aktiv und jeder Lauf
protokolliert den Fehler (Eintrag und Feld, keine Koordinaten). Ein Fehler bei der Bewertung
eines einzelnen Flugs wird wie bei Flugzeugen als `skipped` gezählt; der Flug behält dann die
Begründung „noch nicht bewertet“.
```

Im Abschnitt `## Einstufung (heuristisch)` am Ende anfügen:

```markdown
Die Rolle im Flugroutenvergleich (Abflug/Anflug bezogen auf BER) wird unabhängig davon bestimmt,
siehe [routes.md](routes.md#rolle).
```

Im Abschnitt `## Befehle` den Codeblock ersetzen durch:

```bash
sudo docker compose exec analysis python -m analysis zones            # Zonen laden
sudo docker compose exec analysis python -m analysis procedures       # Verfahren laden
sudo docker compose exec analysis python -m analysis once             # ein Lauf
sudo docker compose exec analysis python -m analysis rebuild --from 2026-11-01 --to 2026-12-01
python scripts/check_procedures.py config/local/procedures.yaml       # Verfahrensdatei prüfen
```

und den Satz danach ersetzen durch: „Zonen- und Verfahrensänderungen wirken nur auf neue Läufe; für zurückliegende Zeiträume `rebuild` ausführen.“

Im Abschnitt `## Bekannte Grenzen` anhängen:

```markdown
- **Flugroutenvergleich:** siehe [routes.md](routes.md#grenzen).
```

- [ ] **Step 4: `docs/data-model.md`** – vor `## Herkunftskette` einfügen:

```markdown
## Flugroutenvergleich (Meilenstein 4)

| Tabelle / View | Bedeutung |
|---|---|
| `procedures` | Verfahren (SID/STAR) mit Ideallinie, Startbahn und -kurs, Betriebsrichtung, Sektor, Gültigkeit; Änderungen erzeugen eine neue Fassung (`superseded_at`) |
| `operating_directions` | Betriebsrichtung je 30-Minuten-Fenster (`west`/`east`/`unknown`) mit Zahl der Stimmen, Anteil der Mehrheit und Begründung |
| `flight_assessments` | eine Zeile je Flug mit Rolle: Bezugszeitpunkt und -kurs, Stimme, Sektor, zugeordnetes Verfahren, Sicherheitsstufe und Begründung, Abweichung (C), Annäherung (B), Prüffall (E), Datenqualität |
| `route_stats_daily` | je Tag (Europe/Berlin), Verfahren und Sicherheitsstufe: Flüge, Abweichungen, Annäherungen, Prüffälle, Median und 95-%-Wert von `max_dev_m` |

`flight_assessments` hängt mit `ON DELETE CASCADE` an `flights`; wird ein Flug neu gebildet,
entsteht auch die Bewertung neu. Abstände in m, Dauern in s; `eval_from`/`eval_to` begrenzen
den bewerteten Abschnitt. Herkunft einer Bewertung: `run_id` → Parameter und Version in
`analysis_runs`; `procedure_id` → Fassung des Verfahrens mit `source` und `airac`;
`ref_geofence_id` → Zonenfassung der Annäherung.
```

- [ ] **Step 5: `docs/dashboard.md`** – in der Tabelle die Zeile „Flugspur“ ersetzen und „Flugrouten“ anhängen:

```markdown
| Flugspur | Spur, Höhe und Geschwindigkeit, Überflüge, zugeordnetes Verfahren mit Ideallinie und Korridor, Bewertung (Link aus „Tiefste Überflüge“ und „Prüffälle“) |
| Flugrouten | Kennzahlen (bewertbar, Abweichungen C, Annäherungen B, Prüffälle E), Betriebsrichtung, Tabelle je Verfahren, Karte mit Ideallinien, Korridor und Spuren, Prüffälle |
```

Nach dem Absatz „Filter „Überflüge: relevante“ …“ einfügen:

```markdown
Im Dashboard „Flugrouten“ wirken die Filter Verfahren, Sicherheit (ab mittel, nur hoch, alle) und
„Nur Prüffälle“ auf Kennzahlen C, B, E, Tabellen und Karte; „Bewertbar“ bezieht sich immer auf
alle An- und Abflüge im Zeitraum. Eine Abweichung ist **kein** Verstoß (siehe
[routes.md](routes.md)). Der Korridor erscheint als Randlinie, weil Grafana aus SQL keine
Flächen zeichnet.
```

- [ ] **Step 6: `docs/deployment-nas.md`** – nach Abschnitt `## 3a. Zonen` einfügen:

````markdown
## 3b. Flugverfahren

Die Tabellen für den Flugroutenvergleich legt `ingest` beim Start an (Migration
`003_routen.sql`); dafür ist nichts zu tun, auch nicht bei einer bestehenden Datenbank.

Verfahren nach [routes.md](routes.md#übertragen-aus-der-aip) aus der AIP übertragen und auf dem
Entwicklungsrechner prüfen (Umgebung wie in der README; Referenzpunkt wie `ANALYSIS_BER_LAT`/
`ANALYSIS_BER_LON` in `nas/.env`):

```bash
python scripts/check_procedures.py config/local/procedures.yaml \
  --ber-lat <ANALYSIS_BER_LAT> --ber-lon <ANALYSIS_BER_LON>
```

Dann die Datei als `config/local/procedures.yaml` in den Repo-Ordner auf dem NAS kopieren
(gitignored, neben der Zonendatei) und laden:

```bash
cd <ssd>/docker/flightdb/repo/nas
sudo docker compose exec analysis python -m analysis procedures
```

Der Befehl prüft die Datei erneut; bei einem Fehler bleibt die bisherige Fassung aktiv. Ohne
Verfahrensdatei läuft die Auswertung ohne Routenvergleich weiter. Für Zeiträume vor dem Laden:
`sudo docker compose exec analysis python -m analysis rebuild --from JJJJ-MM-TT --to JJJJ-MM-TT`.
````

- [ ] **Step 7: `README.md`** – im Status die Zeile zu Meilenstein 4 ersetzen durch:

```markdown
- Meilenstein 4 – Flugroutenvergleich: Software fertig und getestet, Abnahme mit Hardware ausstehend
```

und in der Doku-Tabelle nach `docs/analysis.md` ergänzen:

```markdown
| [docs/routes.md](docs/routes.md) | Flugroutenvergleich: Verfahren, Methodik, Grenzen |
```

- [ ] **Step 8: Prüfen und Commit**

Run: `pytest && ruff format . && ruff check . && git diff --cached --stat`
Expected: alle PASS (`test_analysis_compose_env.py` liest den Parameterabschnitt aus `docs/analysis.md`).

```bash
git add docs/ README.md
git commit -m "Dokumentation: Flugroutenvergleich, ADR 0007, Status Meilenstein 4"
```

---

## Abschluss

- [ ] `pytest` und `pytest -m e2e` grün, `ruff check .` und `ruff format --check .` sauber, `python scripts/check_dashboards.py dashboard/dashboards/*.json` ohne Ausgabe.
- [ ] `git log --format='%an <%ae> | %cn <%ce>' main..m4-routen | sort -u` zeigt nur die noreply-Adresse; keine Attribution in Nachrichten (`git log main..m4-routen --format=%B | grep -i claude` ohne Treffer).
- [ ] `git diff main..m4-routen --stat` enthält keine Datei unter `config/local/` und keine echte Verfahrensdatei.
- [ ] Manuelle Sichtprüfung: E2E-Stack mit `docker compose -f tests/e2e/compose.yml up -d --build` starten, nach rund 8 Minuten `http://localhost:3002` (admin/admin) öffnen, Dashboards „Flugrouten“ und „Flugspur“ (Link aus „Prüffälle“) ansehen, danach `docker compose -f tests/e2e/compose.yml down -v`.
- [ ] Danach superpowers:finishing-a-development-branch.
