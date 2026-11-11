# Meilenstein 3 – Geofences und Dashboard: Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aus den erfassten Positionen Flüge und Überflugereignisse je Zone berechnen und in Grafana als überprüfbare Überflugstatistik darstellen.

**Architecture:** Neuer Dienst `analysis` (Python 3.12, psycopg) auf dem NAS bildet inkrementell Flüge aus `positions`, schneidet ihre Spuren in PostGIS mit den Zonen aus `geofences` und speichert `overflight_events` mit heuristischer Einstufung. Grafana liest über `flightdb_reader`; Dashboards werden aus `dashboard/build_dashboards.py` erzeugt. Zonen kommen aus der lokalen Datei `config/local/geofences.geojson`.

**Tech Stack:** Python 3.12, psycopg 3.2.3, PostgreSQL 16 + PostGIS 3.4, Grafana 13.2.6, Docker Compose, pytest 8.3.3, ruff 0.7.4.

Spezifikation: [2026-11-10-meilenstein-3-geofences-dashboard-design.md](../specs/2026-11-10-meilenstein-3-geofences-dashboard-design.md)

## Global Constraints

- Öffentliches Repo: keine echten Koordinaten, Ortsnamen des Wohnumfelds, Hostnamen, IPs, Zugangsdaten. Testdaten nur synthetisch (Empfänger `TEST`, ICAO24 `ff…`, Orte um 50,0° N / 10,0° O oder im Atlantik).
- Commits: Autor ausschließlich der Repo-Inhaber (noreply-Adresse), **keine** `Co-Authored-By`- oder „Generated with“-Zeilen. Pre-Commit-Hook bleibt aktiv.
- Einheiten wie M2: Höhen ft, Geschwindigkeit kt, Raten ft/min, Abstände m, Zeiten UTC (`timestamptz`).
- Migrationen spielt nur `ingest` ein; `analysis` hat keine Admin-Rechte.
- Relevanzgrenze Standard 10000 ft; Pausenschwelle 600 s; Ausreißer > 800 kt; Kontext 120 s; mind. 5 Positionen; Vertikalrate 300 ft/min; BER-Radius 40000 m; Settle 120 s.
- Grafana `grafana/grafana:13.2.6@sha256:b21409d7951ddcfd63a4b49083e4ef2cc35bc1437d071813bf82bfb238b00bca`, Datenquellen-UID `flightdb`, Typ `grafana-postgresql-datasource`.
- Dashboards ohne Kartenmittelpunkt/Zoom; Geomap-Ansicht `fit`.
- ruff: line-length 100, Regeln E, F, I, B, UP; vor jedem Commit `ruff format .` und `ruff check .`.
- Testbefehle (lokal): `. .venv/bin/activate`, `docker compose -f tests/compose.test.yml up -d`, `export TEST_ADMIN_DSN=postgresql://postgres:test@localhost:55432/postgres`. Colima mountet nur `~`: keine Test-Volumes unter `/tmp`.
- Testdateinamen müssen projektweit eindeutig sein (kein `__init__.py` in `tests/`).

## Dateiübersicht

| Datei | Verantwortung |
|---|---|
| `database/migrations/002_analyse.sql` | Tabellen, Views, Rolle `flightdb_analysis`, Rechte |
| `database/init/10-roles.sh` | LOGIN-Rolle `flightdb_analysis` bei Neuinstallation |
| `analysis/src/analysis/config.py` | Konfiguration aus Umgebungsvariablen |
| `analysis/src/analysis/logjson.py` | JSON-Logging (Kopie aus `ingest`) |
| `analysis/src/analysis/segment.py` | Punkte → Flugabschnitte (rein) |
| `analysis/src/analysis/classify.py` | Einstufung (rein) |
| `analysis/src/analysis/zones.py` | GeoJSON lesen/prüfen, Abgleich mit `geofences` |
| `analysis/src/analysis/events.py` | Durchquerungen per SQL, Kennwerte (rein) |
| `analysis/src/analysis/db.py` | übrige Datenbankzugriffe |
| `analysis/src/analysis/pipeline.py` | Zeitfenster, Lauf, Neuberechnung |
| `analysis/src/analysis/cli.py`, `__main__.py` | Befehle |
| `analysis/Dockerfile` | Container |
| `config/geofences.example.geojson` | Beispielzonen (Atlantik) |
| `scripts/osm_to_geofences.py` | Overpass-JSON → Zonenformat |
| `dashboard/build_dashboards.py` | erzeugt `dashboard/dashboards/*.json` |
| `dashboard/provisioning/…` | Grafana-Datenquelle und Dashboard-Provider |
| `scripts/check_dashboards.py` | verbietet Koordinaten/Zoom in Dashboards |
| `tests/fixtures/synthetic/tracks.py` | synthetische Spuren und Rohdatei-Einträge direkt in die DB |
| `tests/fixtures/dashboard_sql.py` | ersetzt Grafana-Variablen/Makros für Tests |

---

### Task 1: Datenbankschema `002_analyse.sql` und Rolle

**Files:**
- Create: `database/migrations/002_analyse.sql`
- Modify: `database/init/10-roles.sh`
- Modify: `tests/conftest.py`
- Modify: `tests/db/test_schema.py`
- Modify: `tests/e2e/compose.yml` (nur `DB_ANALYSIS_PASSWORD`)
- Modify: `nas/docker-compose.yml`, `nas/.env.example` (nur `DB_ANALYSIS_PASSWORD`)

**Interfaces:**
- Produces: Tabellen `analysis_runs`, `geofences`, `flights`, `overflight_events`; Views `overflights_daily`, `data_coverage_daily`; Rolle `flightdb_analysis`; Fixture-Schlüssel `db_dsns["analysis"]`.

- [ ] **Step 1: Tests schreiben** – in `tests/db/test_schema.py` den Idempotenztest anpassen und neue Tests anhängen:

```python
def test_migrate_is_idempotent(db_dsns):
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        assert migrate(c, MIGRATIONS) == []
        versions = [r[0] for r in c.execute("SELECT version FROM schema_migrations")]
        assert versions == ["001_erfassung.sql", "002_analyse.sql"]
```

```python
def test_analysis_role_reads_positions_but_cannot_write_them(db_dsns):
    with psycopg.connect(db_dsns["analysis"]) as c:
        assert c.execute("SELECT count(*) FROM positions").fetchone() == (0,)
        c.execute(
            "INSERT INTO analysis_runs (kind, algo_version, params, status)"
            " VALUES ('incremental', 'test', '{}', 'running')"
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "INSERT INTO positions (ts, receiver_id, icao24, geom, raw_file_id)"
                " VALUES (now(), 'TEST', 'ff0001', ST_MakePoint(10, 50), 0)"
            )


def test_reader_reads_analysis_views(db_dsns):
    with psycopg.connect(db_dsns["reader"]) as c:
        for view in ("overflights_daily", "data_coverage_daily", "overflight_events"):
            c.execute(f"SELECT * FROM {view} LIMIT 1")


def test_circle_needs_radius(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute(
            "INSERT INTO geofences (name, kind, geom, ref_point) VALUES ('x', 'circle',"
            " ST_Multi(ST_Buffer(ST_MakePoint(10, 50), 0.01))::geometry(MultiPolygon, 4326),"
            " ST_SetSRID(ST_MakePoint(10, 50), 4326))"
        )


def test_coverage_view_subtracts_gaps(db_dsns):
    with psycopg.connect(db_dsns["admin"]) as c:
        c.execute("INSERT INTO receivers (id, label) VALUES ('TEST', 'Test')")
        raw_id = c.execute(
            "INSERT INTO raw_files (receiver_id, path, sha256, size_bytes, period_start,"
            " period_end, status, ingest_version) VALUES ('TEST', 'TEST/a', repeat('a', 64), 1,"
            " '2026-11-09T14:00:00Z', '2026-11-09T16:00:00Z', 'ingested', 'test') RETURNING id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO reception_gaps (receiver_id, gap_start, gap_end, reason, raw_file_id)"
            " VALUES ('TEST', '2026-11-09T15:00:00Z', '2026-11-09T15:10:00Z', 'no_data', %s)",
            (raw_id,),
        )
        row = c.execute(
            "SELECT recorded_s, gap_s, day_s FROM data_coverage_daily WHERE day = '2026-11-09'"
        ).fetchone()
    assert row == (7200, 600, 86400)
```

- [ ] **Step 2: Fixture erweitern** – in `tests/conftest.py` nach den beiden `ALTER ROLE`-Zeilen:

```python
        c.execute("ALTER ROLE flightdb_analysis LOGIN PASSWORD 'test'")
```

und im `yield`-Dict ergänzen:

```python
        "analysis": as_role("flightdb_analysis"),
```

- [ ] **Step 3: Tests laufen lassen, Fehlschlag prüfen**

Run: `pytest tests/db/test_schema.py -v`
Expected: FAIL (`role "flightdb_analysis" does not exist` bzw. fehlende Tabellen).

- [ ] **Step 4: Migration schreiben** – `database/migrations/002_analyse.sql`:

```sql
-- Meilenstein 3: Zonen, Flüge, Überflugereignisse und Analyse-Läufe.
-- Einheiten wie in 001: ft, kt, ft/min; Abstände in m; Zeiten in UTC.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'flightdb_analysis') THEN
    CREATE ROLE flightdb_analysis NOLOGIN;
  END IF;
END
$$;

CREATE TABLE analysis_runs (
  id            bigserial PRIMARY KEY,
  kind          text NOT NULL CHECK (kind IN ('incremental', 'rebuild')),
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  algo_version  text NOT NULL,
  params        jsonb NOT NULL,
  window_from   timestamptz,
  window_to     timestamptz,
  status        text NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
  n_flights     integer,
  n_events      integer,
  n_skipped     integer,
  error         text
);

CREATE TABLE geofences (
  id                    bigserial PRIMARY KEY,
  name                  text NOT NULL,
  kind                  text NOT NULL CHECK (kind IN ('circle', 'polygon')),
  geom                  geometry(MultiPolygon, 4326) NOT NULL,
  ref_point             geometry(Point, 4326) NOT NULL,
  radius_m              real,
  relevance_max_alt_ft  integer NOT NULL DEFAULT 10000,
  source                text,
  valid_from            timestamptz NOT NULL DEFAULT now(),
  valid_to              timestamptz,
  CHECK ((kind = 'circle') = (radius_m IS NOT NULL))
);

CREATE INDEX geofences_geom_gist ON geofences USING gist (geom);
CREATE UNIQUE INDEX geofences_current_name ON geofences (name) WHERE valid_to IS NULL;

CREATE TABLE flights (
  id               bigserial PRIMARY KEY,
  icao24           text NOT NULL,
  callsign         text,
  first_ts         timestamptz NOT NULL,
  last_ts          timestamptz NOT NULL,
  n_positions      integer NOT NULL,
  n_outliers       integer NOT NULL DEFAULT 0,
  track            geometry(LineStringM, 4326) NOT NULL,
  analysis_run_id  bigint NOT NULL REFERENCES analysis_runs (id)
);

CREATE INDEX flights_icao_first ON flights (icao24, first_ts);
CREATE INDEX flights_last_ts ON flights (last_ts);
CREATE INDEX flights_track_gist ON flights USING gist (track);

CREATE TABLE overflight_events (
  id                  bigserial PRIMARY KEY,
  flight_id           bigint NOT NULL REFERENCES flights (id) ON DELETE CASCADE,
  geofence_id         bigint NOT NULL REFERENCES geofences (id),
  entry_ts            timestamptz NOT NULL,
  exit_ts             timestamptz NOT NULL,
  duration_s          real NOT NULL,
  min_dist_m          real NOT NULL,
  closest_ts          timestamptz NOT NULL,
  min_alt_ft          integer,
  alt_at_closest_ft   integer,
  heading_deg         real,
  heading_sector      text,
  category            text NOT NULL
                      CHECK (category IN ('arrival', 'departure', 'overflight', 'unknown')),
  category_basis      jsonb NOT NULL,
  relevant            boolean NOT NULL,
  n_positions_inside  integer NOT NULL,
  max_position_gap_s  real,
  in_reception_gap    boolean NOT NULL,
  analysis_run_id     bigint NOT NULL REFERENCES analysis_runs (id)
);

CREATE INDEX overflight_events_zone_entry ON overflight_events (geofence_id, entry_ts);
CREATE INDEX overflight_events_entry ON overflight_events (entry_ts);
CREATE INDEX overflight_events_flight ON overflight_events (flight_id);

-- Tage in Europe/Berlin; Zonen über den Namen, damit alle Fassungen einer Zone zählen.
CREATE VIEW overflights_daily AS
SELECT
  (e.entry_ts AT TIME ZONE 'Europe/Berlin')::date AS day,
  g.name AS zone,
  e.category,
  e.relevant,
  count(*) AS n_events,
  min(e.min_alt_ft) AS min_alt_ft
FROM overflight_events e
JOIN geofences g ON g.id = e.geofence_id
GROUP BY 1, 2, 3, 4;

-- Aufgezeichnete Sekunden je Tag (eingelesene Dateizeiträume) abzüglich belegter Lücken.
CREATE VIEW data_coverage_daily AS
WITH days AS (
  SELECT
    r.id AS receiver_id,
    d::date AS day,
    d AT TIME ZONE 'Europe/Berlin' AS day_start,
    (d + interval '1 day') AT TIME ZONE 'Europe/Berlin' AS day_end
  FROM receivers r,
    generate_series(
      (SELECT date_trunc('day', min(period_start) AT TIME ZONE 'Europe/Berlin')
         FROM raw_files WHERE status = 'ingested'),
      date_trunc('day', now() AT TIME ZONE 'Europe/Berlin'),
      interval '1 day') AS d
)
SELECT
  days.receiver_id,
  days.day,
  coalesce((SELECT sum(extract(epoch FROM
      least(f.period_end, days.day_end) - greatest(f.period_start, days.day_start)))
    FROM raw_files f
    WHERE f.receiver_id = days.receiver_id AND f.status = 'ingested'
      AND f.period_start < days.day_end AND f.period_end > days.day_start), 0) AS recorded_s,
  coalesce((SELECT sum(extract(epoch FROM
      least(g.gap_end, days.day_end) - greatest(g.gap_start, days.day_start)))
    FROM reception_gaps g
    WHERE g.receiver_id = days.receiver_id
      AND g.gap_start < days.day_end AND g.gap_end > days.day_start), 0) AS gap_s,
  extract(epoch FROM least(days.day_end, now()) - days.day_start) AS day_s
FROM days;

GRANT USAGE ON SCHEMA public TO flightdb_analysis;
GRANT SELECT ON positions, reception_gaps, raw_files, receivers TO flightdb_analysis;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON geofences, flights, overflight_events, analysis_runs TO flightdb_analysis;
GRANT USAGE ON SEQUENCE geofences_id_seq, flights_id_seq, overflight_events_id_seq,
  analysis_runs_id_seq TO flightdb_analysis;
GRANT SELECT ON geofences, flights, overflight_events, analysis_runs,
  overflights_daily, data_coverage_daily TO flightdb_reader;
```

- [ ] **Step 5: Init-Skript erweitern** – `database/init/10-roles.sh` ersetzen durch:

```bash
#!/bin/bash
# Läuft einmalig beim ersten Start des PostGIS-Containers (leeres Datenverzeichnis).
# Legt die Anwendungsrollen mit Passwörtern aus der .env an; Rechte vergibt die Migration.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v ingest_pw="$DB_INGEST_PASSWORD" -v reader_pw="$DB_READONLY_PASSWORD" \
  -v analysis_pw="$DB_ANALYSIS_PASSWORD" <<'SQL'
CREATE ROLE flightdb_ingest LOGIN PASSWORD :'ingest_pw';
CREATE ROLE flightdb_reader LOGIN PASSWORD :'reader_pw';
CREATE ROLE flightdb_analysis LOGIN PASSWORD :'analysis_pw';
SQL
```

In `nas/docker-compose.yml` beim Dienst `postgis` unter `environment` nach `DB_READONLY_PASSWORD` ergänzen: `DB_ANALYSIS_PASSWORD: ${DB_ANALYSIS_PASSWORD}`. In `nas/.env.example` nach `DB_READONLY_PASSWORD=change-me`: `DB_ANALYSIS_PASSWORD=change-me`. In `tests/e2e/compose.yml` beim Dienst `postgis` nach `DB_READONLY_PASSWORD: reader`: `DB_ANALYSIS_PASSWORD: analysis`.

- [ ] **Step 6: Tests laufen lassen**

Run: `pytest tests/db -v`
Expected: alle PASS (inkl. der bestehenden M2-Tests).

- [ ] **Step 7: Lint und Commit**

```bash
ruff format . && ruff check .
git add database/ tests/conftest.py tests/db/test_schema.py tests/e2e/compose.yml nas/
git commit -m "Datenbank: Schema für Zonen, Flüge und Überflugereignisse"
```

---

### Task 2: Paketgerüst `analysis` und Flugbildung `segment`

**Files:**
- Create: `analysis/src/analysis/__init__.py`, `analysis/src/analysis/config.py`, `analysis/src/analysis/logjson.py`, `analysis/src/analysis/segment.py`
- Modify: `pyproject.toml`
- Test: `tests/analysis/test_analysis_config.py`, `tests/analysis/test_segment.py`

**Interfaces:**
- Produces:
  - `analysis.__version__ = "0.1.0"`
  - `Config(db_dsn: str, ber_lat: float, ber_lon: float, zones_file: Path | None = None, interval_s=300, settle_s=120, flight_gap_s=600, max_speed_kt=800.0, context_s=120, min_positions=5, vrate_fpm=300.0, ber_radius_m=40000.0, default_relevance_ft=10000, heartbeat_file=Path("/tmp/analysis-heartbeat"))`, `Config.from_env(env)`, `Config.params() -> dict`
  - `Point(ts: datetime, lat: float, lon: float, alt_ft: int | None, vrate_fpm: int | None, callsign: str | None, on_ground: bool)` (frozen)
  - `Segment(icao24: str, points: list[Point], n_outliers: int = 0)` mit Properties `first_ts`, `last_ts`, `callsign`
  - `haversine_m(lat1, lon1, lat2, lon2) -> float`
  - `segment(icao24: str, points: Iterable[Point], *, gap_s: float, max_speed_kt: float) -> list[Segment]`

- [ ] **Step 1: pytest-Pfad erweitern** – in `pyproject.toml`:

```toml
pythonpath = ["receiver/recorder/src", "ingest/src", "analysis/src", "scripts", "dashboard", "tests/fixtures"]
```

Kommentarzeile oben ändern zu: `# Nur Werkzeugkonfiguration; recorder, ingest und analysis werden als Container gebaut.`

- [ ] **Step 2: Tests schreiben** – `tests/analysis/test_analysis_config.py`:

```python
from pathlib import Path

from analysis.config import Config


def test_from_env_defaults():
    cfg = Config.from_env(
        {"ANALYSIS_DB_DSN": "postgresql://x", "ANALYSIS_BER_LAT": "49.5", "ANALYSIS_BER_LON": "8.5"}
    )
    assert (cfg.ber_lat, cfg.ber_lon) == (49.5, 8.5)
    assert cfg.zones_file is None
    assert (cfg.flight_gap_s, cfg.settle_s, cfg.default_relevance_ft) == (600, 120, 10000)


def test_from_env_overrides_and_params():
    cfg = Config.from_env(
        {
            "ANALYSIS_DB_DSN": "postgresql://x",
            "ANALYSIS_BER_LAT": "49.5",
            "ANALYSIS_BER_LON": "8.5",
            "ANALYSIS_ZONES_FILE": "/zones/geofences.geojson",
            "ANALYSIS_FLIGHT_GAP_S": "30",
            "ANALYSIS_VRATE_FPM": "500",
        }
    )
    assert cfg.zones_file == Path("/zones/geofences.geojson")
    params = cfg.params()
    assert params["flight_gap_s"] == 30 and params["vrate_fpm"] == 500.0
    assert "db_dsn" not in params
```

`tests/analysis/test_segment.py`:

```python
from datetime import UTC, datetime, timedelta

from analysis.segment import Point, haversine_m, segment

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
DEG_LON_M = 71_696.0  # Meter je Grad Länge bei 50° Breite


def pt(s, lat=50.0, east_m=None, alt=3000, cs="TEST01", ground=False):
    lon = 10.0 + (100.0 * s if east_m is None else east_m) / DEG_LON_M
    return Point(T0 + timedelta(seconds=s), lat, lon, alt, 0, cs, ground)


def run(points):
    return segment("ff0001", points, gap_s=600, max_speed_kt=800)


def test_continuous_track_is_one_flight():
    (seg,) = run([pt(s) for s in range(10)])
    assert len(seg.points) == 10 and seg.n_outliers == 0
    assert (seg.first_ts, seg.last_ts) == (T0, T0 + timedelta(seconds=9))


def test_pause_longer_than_gap_splits():
    segs = run([pt(s) for s in range(5)] + [pt(s) for s in range(700, 705)])
    assert [len(s.points) for s in segs] == [5, 5]


def test_callsign_change_splits_but_missing_callsign_does_not():
    points = [pt(s, cs="AAA1") for s in range(3)] + [pt(3, cs=None)]
    points += [pt(s, cs="BBB2") for s in range(4, 8)]
    segs = run(points)
    assert [s.callsign for s in segs] == ["AAA1", "BBB2"]
    assert [len(s.points) for s in segs] == [4, 4]


def test_landing_splits_and_ground_positions_are_dropped():
    points = [pt(s) for s in range(5)] + [pt(s, ground=True) for s in range(5, 10)]
    points += [pt(s) for s in range(10, 15)]
    segs = run(points)
    assert [len(s.points) for s in segs] == [5, 5]
    assert not any(p.on_ground for s in segs for p in s.points)


def test_implausible_jump_is_dropped_as_outlier():
    points = [pt(s) for s in range(10)]
    points[5] = pt(5, lat=51.0)
    (seg,) = run(points)
    assert len(seg.points) == 9 and seg.n_outliers == 1


def test_outlier_as_first_point_is_replaced():
    points = [pt(0, lat=51.0)] + [pt(s) for s in range(1, 10)]
    (seg,) = run(points)
    assert len(seg.points) == 9 and seg.n_outliers == 1
    assert seg.points[0].lat == 50.0


def test_single_positions_are_not_flights():
    assert run([pt(0), pt(1000)]) == []


def test_duplicate_timestamps_are_ignored():
    (seg,) = run([pt(0), pt(0), pt(1)])
    assert len(seg.points) == 2


def test_callsign_is_most_common():
    points = [pt(0, cs=None), pt(1, cs="Y2"), pt(2, cs=None), pt(3, cs="Y2")]
    (seg,) = run(points)
    assert seg.callsign == "Y2"


def test_haversine_one_degree_latitude():
    assert abs(haversine_m(50.0, 10.0, 51.0, 10.0) - 111_195) < 50
```

- [ ] **Step 3: Tests laufen lassen, Fehlschlag prüfen**

Run: `pytest tests/analysis -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis'`.

- [ ] **Step 4: Implementierung**

`analysis/src/analysis/__init__.py`:

```python
__version__ = "0.1.0"
```

`analysis/src/analysis/logjson.py`: unveränderte Kopie von `ingest/src/ingest/logjson.py`:

```bash
cp ingest/src/ingest/logjson.py analysis/src/analysis/logjson.py
```

`analysis/src/analysis/config.py`:

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
)


@dataclass(frozen=True)
class Config:
    db_dsn: str
    ber_lat: float
    ber_lon: float
    zones_file: Path | None = None
    interval_s: int = 300
    settle_s: int = 120
    flight_gap_s: int = 600
    max_speed_kt: float = 800.0
    context_s: int = 120
    min_positions: int = 5
    vrate_fpm: float = 300.0
    ber_radius_m: float = 40000.0
    default_relevance_ft: int = 10000
    heartbeat_file: Path = Path("/tmp/analysis-heartbeat")

    def params(self) -> dict:
        return {name: getattr(self, name) for name in PARAM_FIELDS}

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        zones = env.get("ANALYSIS_ZONES_FILE")
        return cls(
            db_dsn=env["ANALYSIS_DB_DSN"],
            ber_lat=float(env["ANALYSIS_BER_LAT"]),
            ber_lon=float(env["ANALYSIS_BER_LON"]),
            zones_file=Path(zones) if zones else None,
            interval_s=int(env.get("ANALYSIS_INTERVAL_S", "300")),
            settle_s=int(env.get("ANALYSIS_SETTLE_S", "120")),
            flight_gap_s=int(env.get("ANALYSIS_FLIGHT_GAP_S", "600")),
            max_speed_kt=float(env.get("ANALYSIS_MAX_SPEED_KT", "800")),
            context_s=int(env.get("ANALYSIS_CONTEXT_S", "120")),
            min_positions=int(env.get("ANALYSIS_MIN_POSITIONS", "5")),
            vrate_fpm=float(env.get("ANALYSIS_VRATE_FPM", "300")),
            ber_radius_m=float(env.get("ANALYSIS_BER_RADIUS_M", "40000")),
            default_relevance_ft=int(env.get("ANALYSIS_DEFAULT_RELEVANCE_FT", "10000")),
            heartbeat_file=Path(env.get("ANALYSIS_HEARTBEAT_FILE", "/tmp/analysis-heartbeat")),
        )
```

`analysis/src/analysis/segment.py`:

```python
"""Zerlegt die Positionen eines Flugzeugs in zusammenhängende Flüge (ohne Datenbank)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

EARTH_RADIUS_M = 6_371_008.8
KT_TO_MS = 1852 / 3600


@dataclass(frozen=True)
class Point:
    ts: datetime
    lat: float
    lon: float
    alt_ft: int | None
    vrate_fpm: int | None
    callsign: str | None
    on_ground: bool


@dataclass
class Segment:
    icao24: str
    points: list[Point] = field(default_factory=list)
    n_outliers: int = 0

    @property
    def first_ts(self) -> datetime:
        return self.points[0].ts

    @property
    def last_ts(self) -> datetime:
        return self.points[-1].ts

    @property
    def callsign(self) -> str | None:
        names = [p.callsign for p in self.points if p.callsign]
        return Counter(names).most_common(1)[0][0] if names else None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def segment(
    icao24: str, points: Iterable[Point], *, gap_s: float, max_speed_kt: float
) -> list[Segment]:
    """Zeitlich sortierte Positionen → Flüge mit mindestens zwei gültigen Positionen.

    Neuer Flug nach einer Pause > ``gap_s``, bei Wechsel des Rufzeichens oder nach einer
    Landung. Positionen am Boden gehören nicht zur Spur. Positionen, die nur mit mehr als
    ``max_speed_kt`` erreichbar wären, werden als Ausreißer verworfen und gezählt.
    """
    max_speed = max_speed_kt * KT_TO_MS
    segments: list[Segment] = []
    cur: Segment | None = None
    callsign: str | None = None
    landed = False
    for p in points:
        if p.on_ground:
            landed = True
            continue
        last = cur.points[-1] if cur else None
        if (
            cur is None
            or landed
            or (p.ts - last.ts).total_seconds() > gap_s
            or (p.callsign and callsign and p.callsign != callsign)
        ):
            cur = Segment(icao24, [p])
            segments.append(cur)
            callsign, landed = p.callsign, False
            continue
        dt = (p.ts - last.ts).total_seconds()
        if dt <= 0:
            continue
        if haversine_m(last.lat, last.lon, p.lat, p.lon) / dt > max_speed:
            cur.n_outliers += 1
            if len(cur.points) == 1:
                # Ein einzelner Startpunkt kann selbst der Ausreißer sein.
                cur.points[0] = p
                callsign = p.callsign or callsign
            continue
        cur.points.append(p)
        callsign = p.callsign or callsign
    return [s for s in segments if len(s.points) >= 2]
```

- [ ] **Step 5: Tests laufen lassen**

Run: `pytest tests/analysis -v`
Expected: PASS.

- [ ] **Step 6: Lint und Commit**

```bash
ruff format . && ruff check .
git add pyproject.toml analysis/ tests/analysis/
git commit -m "analysis: Paketgerüst, Konfiguration und Flugbildung"
```

---

### Task 3: Einstufung `classify`

**Files:**
- Create: `analysis/src/analysis/classify.py`
- Test: `tests/analysis/test_classify.py`

**Interfaces:**
- Consumes: `Point`, `haversine_m` aus `analysis.segment`
- Produces: `Classification(category: str, basis: dict)` (frozen); `classify(points: list[Point], *, ber_lat: float, ber_lon: float, min_positions: int, vrate_fpm: float, ber_radius_m: float) -> Classification`

- [ ] **Step 1: Tests schreiben** – `tests/analysis/test_classify.py`:

```python
from datetime import UTC, datetime, timedelta

from analysis.classify import classify
from analysis.segment import Point

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
BER = {"ber_lat": 50.0, "ber_lon": 10.0}
OPTS = BER | {"min_positions": 5, "vrate_fpm": 300, "ber_radius_m": 40000}
M_PER_DEG_LAT = 111_195.0


def line(from_km, to_km, vrate, n=10, alt0=5000, with_rate=True, step_s=6):
    """Punkte südlich des Referenzpunkts auf dem Meridian, Abstand von from_km nach to_km."""
    pts = []
    for i in range(n):
        d = from_km + (to_km - from_km) * i / (n - 1)
        alt = round(alt0 + vrate * step_s * i / 60)
        pts.append(
            Point(
                T0 + timedelta(seconds=step_s * i),
                50.0 - d * 1000 / M_PER_DEG_LAT,
                10.0,
                alt,
                vrate if with_rate else None,
                "TEST01",
                False,
            )
        )
    return pts


def test_arrival():
    c = classify(line(30, 20, -800), **OPTS)
    assert c.category == "arrival"
    assert c.basis["vrate_fpm"] == -800 and c.basis["vrate_source"] == "baro_rate"
    assert abs(c.basis["ber_dist_change_m"] + 10_000) < 50
    assert c.basis["thresholds"]["vrate_fpm"] == 300


def test_departure():
    assert classify(line(20, 30, 1500), **OPTS).category == "departure"


def test_level_flight_is_overflight():
    assert classify(line(30, 20, 0), **OPTS).category == "overflight"


def test_far_from_airport_is_overflight():
    assert classify(line(60, 50, -800), **OPTS).category == "overflight"


def test_climbing_while_approaching_is_unknown():
    c = classify(line(30, 20, 1500), **OPTS)
    assert c.category == "unknown" and "widerspricht" in c.basis["reason"]


def test_too_few_positions_is_unknown():
    c = classify(line(30, 20, -800, n=4), **OPTS)
    assert c.category == "unknown" and c.basis["n_positions"] == 4


def test_rate_from_altitude_when_baro_rate_missing():
    c = classify(line(30, 20, -1000, with_rate=False), **OPTS)
    assert c.category == "arrival" and c.basis["vrate_source"] == "altitude"
    assert abs(c.basis["vrate_fpm"] + 1000) <= 2


def test_threshold_is_strict():
    assert classify(line(30, 20, -300), **OPTS).category == "overflight"
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_classify.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis.classify'`.

- [ ] **Step 3: Implementierung** – `analysis/src/analysis/classify.py`:

```python
"""Heuristische Einstufung eines Überflugs als Anflug, Abflug oder sonstiger Flug.

Grundlage sind nur Höhenverlauf und Abstandsänderung zum Flughafen-Referenzpunkt. Die
Einstufung ist keine Verfahrenszuordnung; diese folgt in Meilenstein 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from analysis.segment import Point, haversine_m


@dataclass(frozen=True)
class Classification:
    category: str
    basis: dict


def _vertical_rate(points: list[Point]) -> tuple[float, str]:
    rates = [p.vrate_fpm for p in points if p.vrate_fpm is not None]
    if rates:
        return fmean(rates), "baro_rate"
    first, last = points[0], points[-1]
    dt = (last.ts - first.ts).total_seconds()
    return ((last.alt_ft - first.alt_ft) / dt * 60 if dt > 0 else 0.0), "altitude"


def classify(
    points: list[Point],
    *,
    ber_lat: float,
    ber_lon: float,
    min_positions: int,
    vrate_fpm: float,
    ber_radius_m: float,
) -> Classification:
    with_alt = [p for p in points if p.alt_ft is not None]
    basis: dict = {
        "n_positions": len(with_alt),
        "thresholds": {
            "min_positions": min_positions,
            "vrate_fpm": vrate_fpm,
            "ber_radius_m": ber_radius_m,
        },
    }
    if len(with_alt) < min_positions:
        return Classification("unknown", basis | {"reason": "zu wenige Positionen mit Höhe"})

    vr, source = _vertical_rate(with_alt)
    d_first = haversine_m(with_alt[0].lat, with_alt[0].lon, ber_lat, ber_lon)
    d_last = haversine_m(with_alt[-1].lat, with_alt[-1].lon, ber_lat, ber_lon)
    change = d_last - d_first
    basis |= {
        "vrate_fpm": round(vr),
        "vrate_source": source,
        "ber_dist_m": round(min(d_first, d_last)),
        "ber_dist_change_m": round(change),
    }
    near = min(d_first, d_last) < ber_radius_m
    sinking, climbing = vr < -vrate_fpm, vr > vrate_fpm
    if near and ((sinking and change > 0) or (climbing and change < 0)):
        return Classification(
            "unknown", basis | {"reason": "Höhenverlauf widerspricht Abstandsänderung"}
        )
    if near and sinking and change < 0:
        return Classification("arrival", basis)
    if near and climbing and change > 0:
        return Classification("departure", basis)
    return Classification("overflight", basis)
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/analysis/test_classify.py -v`
Expected: PASS.

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/classify.py tests/analysis/test_classify.py
git commit -m "analysis: heuristische Einstufung Anflug/Abflug"
```

---

### Task 4: Zonen `zones` und Beispieldatei

**Files:**
- Create: `analysis/src/analysis/zones.py`, `config/geofences.example.geojson`
- Test: `tests/analysis/test_zones.py`, `tests/db/test_analysis_zones.py`

**Interfaces:**
- Produces:
  - `ZoneError(ValueError)`
  - `Zone(name, kind, geometry: dict, radius_m: float | None, ref_point: tuple[float, float] | None, relevance_max_alt_ft: int, source: str | None)` – `ref_point` als (lon, lat)
  - `parse_zones(data: dict, default_relevance_ft: int) -> list[Zone]`
  - `read_zones(path: Path, default_relevance_ft: int) -> list[Zone]`
  - `ZoneSync(changed: list[str], removed: list[str])`
  - `load_zones(conn: psycopg.Connection, zones: list[Zone]) -> ZoneSync`

Format der Zonendatei: GeoJSON `FeatureCollection`. Kreis = `Point`-Geometrie + Property `radius_m`. Polygon = `Polygon`/`MultiPolygon`, optional Property `ref_point: [lon, lat]`. Weitere Properties: `name` (Pflicht, eindeutig), `relevance_max_alt_ft`, `source`.

- [ ] **Step 1: Unit-Tests schreiben** – `tests/analysis/test_zones.py`:

```python
import json

import pytest
from analysis.zones import ZoneError, parse_zones, read_zones

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-31, 44], [-30.9, 44], [-30.9, 44.1], [-31, 44.1], [-31, 44]]],
}


def fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def feature(geometry, **props):
    return {"type": "Feature", "geometry": geometry, "properties": props}


def test_circle_and_polygon():
    zones = parse_zones(
        fc(
            feature({"type": "Point", "coordinates": [-30.0, 45.0]}, name="Kreis", radius_m=3000),
            feature(SQUARE, name="Feld", relevance_max_alt_ft=5000, source="Test"),
        ),
        default_relevance_ft=10000,
    )
    circle, square = zones
    assert (circle.kind, circle.radius_m, circle.ref_point) == ("circle", 3000, (-30.0, 45.0))
    assert circle.relevance_max_alt_ft == 10000
    assert (square.kind, square.ref_point, square.relevance_max_alt_ft) == ("polygon", None, 5000)
    assert square.source == "Test"


def test_polygon_ref_point():
    (z,) = parse_zones(fc(feature(SQUARE, name="Feld", ref_point=[-30.95, 44.05])), 10000)
    assert z.ref_point == (-30.95, 44.05)


@pytest.mark.parametrize(
    "data, message",
    [
        ({"type": "Feature"}, "FeatureCollection"),
        (fc(), "keine Zonen"),
        (fc(feature(SQUARE)), "name"),
        (fc(feature(SQUARE, name="A"), feature(SQUARE, name="A")), "doppelt"),
        (fc(feature({"type": "Point", "coordinates": [-30, 45]}, name="K")), "radius_m"),
        (fc(feature({"type": "Point", "coordinates": [-30, 45]}, name="K", radius_m=0)), "radius_m"),
        (fc(feature({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, name="L")), "Typ"),
        (fc(feature(SQUARE, name="F", ref_point=[200, 44])), "ref_point"),
    ],
)
def test_invalid_zones(data, message):
    with pytest.raises(ZoneError, match=message):
        parse_zones(data, 10000)


def test_example_file_is_valid():
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / "config" / "geofences.example.geojson"
    zones = read_zones(example, 10000)
    assert {z.kind for z in zones} == {"circle", "polygon"}
    # Beispiel liegt im Atlantik, weit weg von jedem echten Ort.
    assert all(z.ref_point is None or z.ref_point[0] < -20 for z in zones)


def test_read_zones_reports_bad_json(tmp_path):
    p = tmp_path / "z.geojson"
    p.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(ZoneError, match="JSON"):
        read_zones(p, 10000)
    p.write_text(json.dumps(fc()), encoding="utf-8")
    with pytest.raises(ZoneError):
        read_zones(p, 10000)
```

- [ ] **Step 2: DB-Tests schreiben** – `tests/db/test_analysis_zones.py`:

```python
import math

import psycopg
import pytest
from analysis.zones import Zone, ZoneError, load_zones

pytestmark = pytest.mark.db


def circle(name="Testzone", radius=5000.0, relevance=10000):
    return Zone(
        name, "circle", {"type": "Point", "coordinates": [10.0, 50.0]}, radius, (10.0, 50.0),
        relevance, "Test",
    )


def square(name="Feld", ref=None):
    ring = [[10.0, 50.0], [10.1, 50.0], [10.1, 50.1], [10.0, 50.1], [10.0, 50.0]]
    return Zone(name, "polygon", {"type": "Polygon", "coordinates": [ring]}, None, ref, 10000, None)


def rows(dsn):
    with psycopg.connect(dsn) as c:
        return c.execute(
            "SELECT name, radius_m, valid_to IS NULL FROM geofences ORDER BY id"
        ).fetchall()


def test_circle_area_and_ref_point(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        assert load_zones(c, [circle()]).changed == ["Testzone"]
        area, ref_ok = c.execute(
            "SELECT ST_Area(geom::geography), ST_Equals(ref_point, ST_SetSRID("
            "ST_MakePoint(10, 50), 4326)) FROM geofences"
        ).fetchone()
    assert abs(area / (math.pi * 5000**2) - 1) < 0.005
    assert ref_ok


def test_unchanged_reload_keeps_version(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_zones(c, [circle()])
        result = load_zones(c, [circle()])
    assert (result.changed, result.removed) == ([], [])
    assert rows(db_dsns["admin"]) == [("Testzone", 5000.0, True)]


def test_changed_zone_gets_new_version(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_zones(c, [circle()])
        assert load_zones(c, [circle(radius=3000)]).changed == ["Testzone"]
    assert rows(db_dsns["admin"]) == [("Testzone", 5000.0, False), ("Testzone", 3000.0, True)]


def test_removed_zone_is_closed(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_zones(c, [circle(), square()])
        assert load_zones(c, [circle()]).removed == ["Feld"]
    assert ("Feld", None, False) in rows(db_dsns["admin"])


def test_polygon_default_ref_point_inside(db_dsns):
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        load_zones(c, [square()])
        assert c.execute("SELECT ST_Within(ref_point, geom) FROM geofences").fetchone() == (True,)


def test_invalid_polygon_writes_nothing(db_dsns):
    bowtie = [[10.0, 50.0], [10.1, 50.1], [10.1, 50.0], [10.0, 50.1], [10.0, 50.0]]
    bad = Zone("Schleife", "polygon", {"type": "Polygon", "coordinates": [bowtie]}, None, None,
               10000, None)
    with psycopg.connect(db_dsns["analysis"], autocommit=True) as c:
        with pytest.raises(ZoneError, match="ungültig"):
            load_zones(c, [circle(), bad])
    assert rows(db_dsns["admin"]) == []
```

- [ ] **Step 3: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_zones.py tests/db/test_analysis_zones.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis.zones'`.

- [ ] **Step 4: Beispieldatei** – `config/geofences.example.geojson` (erfundene Zonen im Atlantik):

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [-30.0, 45.0] },
      "properties": {
        "name": "Beispiel Kreis",
        "radius_m": 3000,
        "relevance_max_alt_ft": 10000,
        "source": "erfunden"
      }
    },
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[-31.0, 44.0], [-30.9, 44.0], [-30.9, 44.1], [-31.0, 44.1], [-31.0, 44.0]]]
      },
      "properties": {
        "name": "Beispiel Gebiet",
        "ref_point": [-30.95, 44.05],
        "source": "erfunden"
      }
    }
  ]
}
```

- [ ] **Step 5: Implementierung** – `analysis/src/analysis/zones.py`:

```python
"""Überwachungszonen: GeoJSON lesen und prüfen, mit ``geofences`` abgleichen.

Kreise (Point + ``radius_m``) werden in PostGIS geodätisch in ein 64-Eck umgerechnet.
Geänderte Zonen erhalten eine neue Fassung; die alte wird mit ``valid_to`` geschlossen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import psycopg


class ZoneError(ValueError):
    pass


@dataclass(frozen=True)
class Zone:
    name: str
    kind: str  # circle | polygon
    geometry: dict
    radius_m: float | None
    ref_point: tuple[float, float] | None  # (lon, lat)
    relevance_max_alt_ft: int
    source: str | None


@dataclass(frozen=True)
class ZoneSync:
    changed: list[str]
    removed: list[str]


def _lonlat(value, what: str) -> tuple[float, float]:
    if (
        not isinstance(value, list | tuple)
        or len(value) < 2
        or not all(isinstance(v, int | float) for v in value[:2])
        or not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90)
    ):
        raise ZoneError(f"{what}: [lon, lat] erwartet")
    return float(value[0]), float(value[1])


def parse_zones(data: dict, default_relevance_ft: int) -> list[Zone]:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ZoneError("GeoJSON FeatureCollection erwartet")
    zones: list[Zone] = []
    for i, feature in enumerate(data.get("features") or []):
        props = feature.get("properties") or {}
        name = props.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ZoneError(f"Feature {i}: Property name fehlt")
        if any(z.name == name for z in zones):
            raise ZoneError(f"Zone {name!r} doppelt")
        geometry = feature.get("geometry") or {}
        gtype = geometry.get("type")
        if gtype == "Point":
            radius = props.get("radius_m")
            if not isinstance(radius, int | float) or radius <= 0:
                raise ZoneError(f"{name}: Kreis braucht radius_m > 0")
            kind, radius_m = "circle", float(radius)
            ref = _lonlat(geometry.get("coordinates"), f"{name}: Mittelpunkt")
        elif gtype in ("Polygon", "MultiPolygon"):
            kind, radius_m = "polygon", None
            ref = props.get("ref_point")
            ref = None if ref is None else _lonlat(ref, f"{name}: ref_point")
        else:
            raise ZoneError(f"{name}: Typ {gtype!r} nicht unterstützt")
        zones.append(
            Zone(
                name=name,
                kind=kind,
                geometry=geometry,
                radius_m=radius_m,
                ref_point=ref,
                relevance_max_alt_ft=int(props.get("relevance_max_alt_ft", default_relevance_ft)),
                source=props.get("source"),
            )
        )
    if not zones:
        raise ZoneError("keine Zonen definiert")
    return zones


def read_zones(path: Path, default_relevance_ft: int) -> list[Zone]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ZoneError(f"{path}: kein gültiges JSON ({e})") from e
    return parse_zones(data, default_relevance_ft)


_GEOM = """
SELECT s.g, coalesce(ST_SetSRID(ST_MakePoint(%(ref_lon)s::float8, %(ref_lat)s::float8), 4326),
                     ST_PointOnSurface(s.g)),
       ST_IsValid(s.g), ST_IsValidReason(s.g)
FROM (
  SELECT CASE WHEN %(kind)s = 'circle'
    THEN ST_Multi(ST_Buffer(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326)::geography,
                            %(radius_m)s::float8, 'quad_segs=16')::geometry)
    ELSE ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326))
  END AS g
) s
"""

_CURRENT = """
SELECT id,
       ST_Equals(geom, %(g)s::geometry) AND ST_Equals(ref_point, %(ref)s::geometry)
       AND kind = %(kind)s AND radius_m IS NOT DISTINCT FROM %(radius_m)s::real
       AND relevance_max_alt_ft = %(relevance)s AND source IS NOT DISTINCT FROM %(source)s
FROM geofences WHERE name = %(name)s AND valid_to IS NULL
"""

_INSERT = """
INSERT INTO geofences (name, kind, geom, ref_point, radius_m, relevance_max_alt_ft, source)
VALUES (%(name)s, %(kind)s, %(g)s::geometry, %(ref)s::geometry, %(radius_m)s,
        %(relevance)s, %(source)s)
"""


def load_zones(conn: psycopg.Connection, zones: list[Zone]) -> ZoneSync:
    """Gleicht alle Zonen in einer Transaktion ab; fehlende Zonen werden geschlossen."""
    changed: list[str] = []
    with conn.transaction():
        for z in zones:
            params = {
                "name": z.name,
                "kind": z.kind,
                "geometry": json.dumps(z.geometry),
                "radius_m": z.radius_m,
                "ref_lon": None if z.ref_point is None else z.ref_point[0],
                "ref_lat": None if z.ref_point is None else z.ref_point[1],
                "relevance": z.relevance_max_alt_ft,
                "source": z.source,
            }
            try:
                g, ref, valid, reason = conn.execute(_GEOM, params).fetchone()
            except psycopg.errors.DataException as e:
                raise ZoneError(f"{z.name}: Geometrie ungültig ({e})") from e
            if not valid:
                raise ZoneError(f"{z.name}: Geometrie ungültig ({reason})")
            params |= {"g": g, "ref": ref}
            current = conn.execute(_CURRENT, params).fetchone()
            if current and current[1]:
                continue
            if current:
                conn.execute("UPDATE geofences SET valid_to = now() WHERE id = %s", (current[0],))
            conn.execute(_INSERT, params)
            changed.append(z.name)
        removed = conn.execute(
            "UPDATE geofences SET valid_to = now()"
            " WHERE valid_to IS NULL AND NOT (name = ANY(%s)) RETURNING name",
            ([z.name for z in zones],),
        ).fetchall()
    return ZoneSync(changed, sorted(r[0] for r in removed))
```

- [ ] **Step 6: Tests laufen lassen**

Run: `pytest tests/analysis/test_zones.py tests/db/test_analysis_zones.py -v`
Expected: PASS.

- [ ] **Step 7: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/zones.py config/geofences.example.geojson tests/analysis/test_zones.py tests/db/test_analysis_zones.py
git commit -m "analysis: Zonen aus GeoJSON laden und versionieren"
```

---

### Task 5: Überflugereignisse `events`, Datenbankzugriffe `db` und Testspuren

**Files:**
- Create: `analysis/src/analysis/events.py`, `analysis/src/analysis/db.py`, `tests/fixtures/synthetic/tracks.py`
- Test: `tests/analysis/test_events.py`, `tests/db/test_analysis_events.py`

**Interfaces:**
- Consumes: `Point`, `Segment` (Task 2), `classify` (Task 3), `Config` (Task 2), `load_zones`, `Zone` (Task 4)
- Produces:
  - `events.Crossing(geofence_id: int, entry: datetime, exit: datetime, closest: datetime, min_dist_m: float, heading_deg: float | None)`
  - `events.crossings(conn, flight_id: int) -> list[Crossing]`
  - `events.sector(heading: float | None) -> str | None`
  - `events.interp_alt(points: list[Point], ts: datetime) -> float | None`
  - `events.build_event(c: Crossing, points: list[Point], relevance_ft: int, cfg: Config) -> dict` (Schlüssel = Spalten von `overflight_events` ohne `id`, `flight_id`, `analysis_run_id`, `in_reception_gap`)
  - `db.Counts(flights=0, events=0, skipped=0)` (dataclass, veränderbar)
  - `db.schema_ready(conn) -> bool`, `db.try_lock(conn) -> bool`, `db.unlock(conn)`
  - `db.start_run(conn, kind, version, params, window_from, window_to) -> int`
  - `db.finish_run(conn, run_id, status, counts: Counts, error: str | None = None)`
  - `db.last_incremental(conn) -> tuple[datetime, datetime] | None` (window_to, started_at)
  - `db.data_end(conn) -> datetime | None`, `db.pending_starts(conn) -> list[datetime]`
  - `db.late_start(conn, since: datetime, before: datetime) -> datetime | None`
  - `db.first_position_ts(conn) -> datetime | None`
  - `db.delete_flights(conn, *, last_from: datetime, first_to: datetime | None = None) -> dict[str, tuple[datetime, datetime]]`
  - `db.aircraft_points(conn, start, end, ranges: dict[str, tuple[datetime, datetime]]) -> Iterator[tuple[str, list[Point]]]`
  - `db.current_zones(conn) -> dict[int, int]` (id → Relevanzgrenze)
  - `db.insert_flight(conn, run_id: int, seg: Segment) -> int`
  - `db.in_reception_gap(conn, start: datetime, end: datetime) -> bool`
  - `db.insert_event(conn, run_id: int, flight_id: int, event: dict) -> None`
  - Fixture `tracks`: `m_per_deg(lat) -> (m_lat, m_lon)`, `offset(lat, lon, north_m, east_m) -> (lat, lon)`, `straight(start, lat, lon, heading_deg, speed_kt, n, *, step_s=1.0, alt_ft=3000, vrate_fpm=0, icao24="ff0001", callsign="TEST01") -> list[dict]`, `insert_positions(dsn, rows, receiver_id="TEST")`, `add_raw_file(dsn, start, end, status="ingested", receiver_id="TEST") -> int`

- [ ] **Step 1: Testspuren-Fixture** – `tests/fixtures/synthetic/tracks.py`:

```python
"""Synthetische Flugspuren direkt in ``positions`` (ohne Rohdateien) für Analyse-Tests.

Koordinaten um 50° N / 10° O sind frei gewählt; ICAO24 beginnt mit ``ff``.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta

import psycopg

from ingest.db import ensure_partitions, ensure_receiver

A = 6_378_137.0
E2 = 6.69437999014e-3
KT_TO_MS = 1852 / 3600


def m_per_deg(lat: float) -> tuple[float, float]:
    """Meter je Grad Breite und Länge auf dem WGS84-Ellipsoid."""
    s = math.sin(math.radians(lat)) ** 2
    w = math.sqrt(1 - E2 * s)
    return (
        math.pi * A * (1 - E2) / (180 * w**3),
        math.pi * A * math.cos(math.radians(lat)) / (180 * w),
    )


def offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    m_lat, m_lon = m_per_deg(lat)
    return lat + north_m / m_lat, lon + east_m / m_lon


def straight(
    start: datetime,
    lat: float,
    lon: float,
    heading_deg: float,
    speed_kt: float,
    n: int,
    *,
    step_s: float = 1.0,
    alt_ft: int | None = 3000,
    vrate_fpm: int = 0,
    icao24: str = "ff0001",
    callsign: str | None = "TEST01",
) -> list[dict]:
    """``n`` Positionen im Abstand ``step_s`` mit konstantem Kurs (lokal linear)."""
    m_lat, m_lon = m_per_deg(lat)
    h = math.radians(heading_deg)
    rows = []
    for i in range(n):
        d = speed_kt * KT_TO_MS * step_s * i
        rows.append(
            {
                "ts": start + timedelta(seconds=step_s * i),
                "icao24": icao24,
                "callsign": callsign,
                "lat": lat + d * math.cos(h) / m_lat,
                "lon": lon + d * math.sin(h) / m_lon,
                "alt_baro_ft": None if alt_ft is None else round(alt_ft + vrate_fpm * step_s * i / 60),
                "baro_rate_fpm": None if alt_ft is None else vrate_fpm,
                "on_ground": False,
            }
        )
    return rows


def insert_positions(dsn: str, rows: list[dict], receiver_id: str = "TEST") -> None:
    with psycopg.connect(dsn, autocommit=True) as c:
        ensure_receiver(c, receiver_id)
        ensure_partitions(c, min(r["ts"] for r in rows), max(r["ts"] for r in rows))
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO positions (ts, receiver_id, icao24, callsign, geom, on_ground,"
                " alt_baro_ft, baro_rate_fpm, raw_file_id) VALUES (%(ts)s, %(rid)s, %(icao24)s,"
                " %(callsign)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326), %(on_ground)s,"
                " %(alt_baro_ft)s, %(baro_rate_fpm)s, 0)",
                [r | {"rid": receiver_id} for r in rows],
            )


def add_raw_file(
    dsn: str,
    start: datetime,
    end: datetime,
    status: str = "ingested",
    receiver_id: str = "TEST",
) -> int:
    """Eintrag in ``raw_files``; bei anderem Status als ``ingested`` ohne Zeitraum."""
    ingested = status == "ingested"
    with psycopg.connect(dsn, autocommit=True) as c:
        ensure_receiver(c, receiver_id)
        return c.execute(
            "INSERT INTO raw_files (receiver_id, path, sha256, size_bytes, period_start,"
            " period_end, status, ingest_version) VALUES (%s, %s, %s, 1, %s, %s, %s, 'test')"
            " RETURNING id",
            (
                receiver_id,
                f"{receiver_id}/{start:%Y/%m/%d}/{start:%Y%m%dT%H%M%SZ}.ndjson.gz",
                uuid.uuid4().hex * 2,
                start if ingested else None,
                end if ingested else None,
                status,
            ),
        ).fetchone()[0]
```

- [ ] **Step 2: Unit-Tests für die reinen Funktionen** – `tests/analysis/test_events.py`:

```python
from datetime import UTC, datetime, timedelta

from analysis.config import Config
from analysis.events import Crossing, build_event, interp_alt, sector
from analysis.segment import Point

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
CFG = Config(db_dsn="unused", ber_lat=49.0, ber_lon=8.0)


def t(s):
    return T0 + timedelta(seconds=s)


def pts(alts, step=10):
    return [Point(t(i * step), 50.0, 10.0 + i / 1000, a, 0, "TEST01", False) for i, a in enumerate(alts)]


def test_sector():
    assert [sector(h) for h in (0, 22.4, 22.6, 90, 180, 270, 337.6, None)] == [
        "N", "N", "NO", "O", "S", "W", "N", None,
    ]


def test_interp_alt():
    points = pts([3000, 2000, None, 1000])
    assert interp_alt(points, t(5)) == 2500
    assert interp_alt(points, t(25)) == 1250  # überspringt Position ohne Höhe
    assert interp_alt(points, t(-5)) == 3000  # vor Beginn: erster Wert
    assert interp_alt(pts([None, None]), t(5)) is None


def test_build_event_values():
    points = pts([3000, 2500, 2000, 2500, 3000, 3000, 3000, 3000])
    c = Crossing(7, t(5), t(35), t(20), 1234.5, 90.0)
    ev = build_event(c, points, relevance_ft=2200, cfg=CFG)
    assert ev["geofence_id"] == 7
    assert ev["duration_s"] == 30
    assert ev["min_alt_ft"] == 2000 and ev["alt_at_closest_ft"] == 2000
    assert ev["relevant"] is True
    assert ev["n_positions_inside"] == 3
    assert ev["max_position_gap_s"] == 10
    assert ev["heading_sector"] == "O"
    assert ev["category"] in ("overflight", "unknown")
    assert "thresholds" in ev["category_basis"]


def test_not_relevant_above_limit():
    ev = build_event(Crossing(1, t(5), t(35), t(20), 0, 90.0), pts([9000] * 8), 2200, CFG)
    assert ev["relevant"] is False


def test_zone_between_positions_uses_interpolation():
    points = pts([3000, 2000], step=60)
    ev = build_event(Crossing(1, t(20), t(40), t(30), 10, 0.0), points, 10000, CFG)
    assert ev["n_positions_inside"] == 0
    assert ev["min_alt_ft"] == 2333  # Austritt bei 40 s: 3000 - 1000 * 40/60
    assert ev["max_position_gap_s"] == 60
```

- [ ] **Step 3: DB-Tests für Durchquerungen** – `tests/db/test_analysis_events.py`:

```python
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from analysis import db, events
from analysis.config import Config
from analysis.segment import segment
from analysis.zones import Zone, load_zones
from synthetic.tracks import add_raw_file, insert_positions, offset, straight

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
SPEED_MS = 200 * 1852 / 3600
HALF_CHORD = (5000**2 - 2000**2) ** 0.5


def zone():
    return Zone("Testzone", "circle", {"type": "Point", "coordinates": [10.0, 50.0]}, 5000.0,
                (10.0, 50.0), 10000, "Test")


def east_track(start=T0, north_m=2000, icao="ff0001"):
    lat, lon = offset(50.0, 10.0, north_m, -20000)
    return straight(start, lat, lon, 90, 200, 400, icao24=icao)


def crossings_for(dsns, rows):
    insert_positions(dsns["admin"], rows)
    cfg = Config(db_dsn=dsns["analysis"], ber_lat=49.0, ber_lon=8.0)
    with psycopg.connect(dsns["analysis"], autocommit=True) as c:
        load_zones(c, [zone()])
        run_id = db.start_run(c, "incremental", "test", cfg.params(), T0, T0)
        found = []
        with c.transaction():
            for icao, pts in db.aircraft_points(c, T0, T0 + timedelta(hours=1), {}):
                for seg in segment(icao, pts, gap_s=600, max_speed_kt=800):
                    fid = db.insert_flight(c, run_id, seg)
                    found += [(seg, cr) for cr in events.crossings(c, fid)]
    return found


def test_straight_crossing_matches_geometry(db_dsns):
    ((seg, c),) = crossings_for(db_dsns, east_track())
    expect_entry = (20000 - HALF_CHORD) / SPEED_MS
    expect_exit = (20000 + HALF_CHORD) / SPEED_MS
    assert abs((c.entry - T0).total_seconds() - expect_entry) < 1
    assert abs((c.exit - T0).total_seconds() - expect_exit) < 1
    assert abs((c.closest - T0).total_seconds() - 20000 / SPEED_MS) < 1
    assert abs(c.min_dist_m - 2000) < 25
    assert events.sector(c.heading_deg) == "O"
    assert len(seg.points) == 400


def test_near_miss_has_no_crossing(db_dsns):
    assert crossings_for(db_dsns, east_track(north_m=6000)) == []


def test_two_passes_give_two_crossings(db_dsns):
    back_lat, back_lon = offset(50.0, 10.0, -2000, 21000)
    # 60 s für den Wechsel auf die Gegenbahn: 4 km Versatz, sonst wäre es ein Ausreißer.
    rows = east_track() + straight(T0 + timedelta(seconds=460), back_lat, back_lon, 270, 200, 400)
    found = crossings_for(db_dsns, rows)
    assert [events.sector(c.heading_deg) for _, c in found] == ["O", "W"]
    assert found[0][1].exit < found[1][1].entry


def test_reception_gap_detection(db_dsns):
    raw_id = add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        c.execute(
            "INSERT INTO reception_gaps (receiver_id, gap_start, gap_end, reason, raw_file_id)"
            " VALUES ('TEST', %s, %s, 'no_data', %s)",
            (T0 + timedelta(seconds=180), T0 + timedelta(seconds=200), raw_id),
        )
    with psycopg.connect(db_dsns["analysis"]) as c:
        assert db.in_reception_gap(c, T0 + timedelta(seconds=150), T0 + timedelta(seconds=240))
        assert not db.in_reception_gap(c, T0, T0 + timedelta(seconds=100))
```

- [ ] **Step 4: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_events.py tests/db/test_analysis_events.py -v`
Expected: FAIL mit `ImportError` (`analysis.events`, `analysis.db`).

- [ ] **Step 5: `events.py`**

```python
"""Zonendurchquerungen eines Flugs: Geometrie in PostGIS, Kennwerte in Python."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg

from analysis.classify import classify
from analysis.config import Config
from analysis.segment import Point

SECTORS = ("N", "NO", "O", "SO", "S", "SW", "W", "NW")

# Teilstücke der Spur innerhalb jeder aktuellen Zone; Zeitpunkte über den M-Wert (Unix-Zeit).
_CROSSINGS = """
WITH f AS (SELECT track FROM flights WHERE id = %(flight_id)s),
parts AS (
  SELECT z.id, z.ref_point, (ST_Dump(ST_Intersection(ST_Force2D(f.track), z.geom))).geom AS part
  FROM geofences z, f
  WHERE z.valid_to IS NULL AND ST_Intersects(z.geom, f.track)
)
SELECT parts.id,
  ST_InterpolatePoint(f.track, ST_StartPoint(part)),
  ST_InterpolatePoint(f.track, ST_EndPoint(part)),
  ST_Distance(part::geography, ref_point::geography),
  ST_InterpolatePoint(f.track, ST_ClosestPoint(part, ref_point)),
  degrees(ST_Azimuth(ST_StartPoint(part)::geography, ST_EndPoint(part)::geography))
FROM parts, f
WHERE GeometryType(part) = 'LINESTRING'
"""


@dataclass(frozen=True)
class Crossing:
    geofence_id: int
    entry: datetime
    exit: datetime
    closest: datetime
    min_dist_m: float
    heading_deg: float | None


def _ts(m: float) -> datetime:
    return datetime.fromtimestamp(m, UTC)


def crossings(conn: psycopg.Connection, flight_id: int) -> list[Crossing]:
    out = []
    for gid, m_start, m_end, dist, m_closest, heading in conn.execute(
        _CROSSINGS, {"flight_id": flight_id}
    ):
        if m_start > m_end:  # Teilstück entgegen der Flugrichtung geliefert
            m_start, m_end = m_end, m_start
            heading = None if heading is None else (heading + 180) % 360
        out.append(Crossing(gid, _ts(m_start), _ts(m_end), _ts(m_closest), dist, heading))
    return sorted(out, key=lambda c: (c.entry, c.geofence_id))


def sector(heading: float | None) -> str | None:
    if heading is None:
        return None
    return SECTORS[int(((heading % 360) + 22.5) // 45) % 8]


def interp_alt(points: list[Point], ts: datetime) -> float | None:
    """Höhe zum Zeitpunkt ``ts``, linear zwischen den Nachbarpositionen mit Höhe."""
    before = next((p for p in reversed(points) if p.ts <= ts and p.alt_ft is not None), None)
    after = next((p for p in points if p.ts >= ts and p.alt_ft is not None), None)
    if before is None or after is None:
        known = before or after
        return None if known is None else float(known.alt_ft)
    span = (after.ts - before.ts).total_seconds()
    if span == 0:
        return float(before.alt_ft)
    f = (ts - before.ts).total_seconds() / span
    return before.alt_ft + f * (after.alt_ft - before.alt_ft)


def build_event(c: Crossing, points: list[Point], relevance_ft: int, cfg: Config) -> dict:
    inside = [p for p in points if c.entry <= p.ts <= c.exit]
    alts = [float(p.alt_ft) for p in inside if p.alt_ft is not None]
    alts += [a for a in (interp_alt(points, c.entry), interp_alt(points, c.exit)) if a is not None]
    min_alt = round(min(alts)) if alts else None
    at_closest = interp_alt(points, c.closest)

    before = next((p for p in reversed(points) if p.ts <= c.entry), None)
    after = next((p for p in points if p.ts >= c.exit), None)
    seq = [p.ts for p in ([before] if before else []) + inside + ([after] if after else [])]
    gaps = [(b - a).total_seconds() for a, b in zip(seq, seq[1:], strict=False)]

    ctx = timedelta(seconds=cfg.context_s)
    cls = classify(
        [p for p in points if c.entry - ctx <= p.ts <= c.exit + ctx],
        ber_lat=cfg.ber_lat,
        ber_lon=cfg.ber_lon,
        min_positions=cfg.min_positions,
        vrate_fpm=cfg.vrate_fpm,
        ber_radius_m=cfg.ber_radius_m,
    )
    return {
        "geofence_id": c.geofence_id,
        "entry_ts": c.entry,
        "exit_ts": c.exit,
        "duration_s": (c.exit - c.entry).total_seconds(),
        "min_dist_m": c.min_dist_m,
        "closest_ts": c.closest,
        "min_alt_ft": min_alt,
        "alt_at_closest_ft": None if at_closest is None else round(at_closest),
        "heading_deg": c.heading_deg,
        "heading_sector": sector(c.heading_deg),
        "category": cls.category,
        "category_basis": cls.basis,
        "relevant": min_alt is None or min_alt <= relevance_ft,
        "n_positions_inside": len(inside),
        "max_position_gap_s": max(gaps) if gaps else None,
    }
```

- [ ] **Step 6: `db.py`**

```python
"""Datenbankzugriffe von analysis (Rolle flightdb_analysis)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby
from operator import itemgetter

import psycopg
from psycopg.types.json import Jsonb

from analysis.segment import Point, Segment

LOCK_KEY = 720301  # Advisory-Lock: nur ein Lauf gleichzeitig
_FILE_START = re.compile(r"(\d{8}T\d{6}Z)")


@dataclass
class Counts:
    flights: int = 0
    events: int = 0
    skipped: int = 0


def schema_ready(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT to_regclass('analysis_runs')").fetchone()[0] is not None


def try_lock(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]


def unlock(conn: psycopg.Connection) -> None:
    conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def start_run(
    conn: psycopg.Connection,
    kind: str,
    version: str,
    params: dict,
    window_from: datetime,
    window_to: datetime,
) -> int:
    return conn.execute(
        "INSERT INTO analysis_runs (kind, algo_version, params, window_from, window_to, status)"
        " VALUES (%s, %s, %s, %s, %s, 'running') RETURNING id",
        (kind, version, Jsonb(params), window_from, window_to),
    ).fetchone()[0]


def finish_run(
    conn: psycopg.Connection, run_id: int, status: str, counts: Counts, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE analysis_runs SET status = %s, finished_at = now(), n_flights = %s,"
        " n_events = %s, n_skipped = %s, error = %s WHERE id = %s",
        (status, counts.flights, counts.events, counts.skipped, error, run_id),
    )


def last_incremental(conn: psycopg.Connection) -> tuple[datetime, datetime] | None:
    """(window_to, started_at) des letzten erfolgreichen inkrementellen Laufs."""
    return conn.execute(
        "SELECT window_to, started_at FROM analysis_runs"
        " WHERE kind = 'incremental' AND status = 'ok' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def data_end(conn: psycopg.Connection) -> datetime | None:
    return conn.execute(
        "SELECT max(period_end) FROM raw_files WHERE status = 'ingested'"
    ).fetchone()[0]


def pending_starts(conn: psycopg.Connection) -> list[datetime]:
    """Beginn registrierter, noch nicht eingelesener Dateien (aus dem Dateinamen)."""
    starts = []
    for (path,) in conn.execute("SELECT path FROM raw_files WHERE status <> 'ingested'"):
        m = _FILE_START.search(path.rsplit("/", 1)[-1])
        if m:
            starts.append(datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
    return starts


def late_start(conn: psycopg.Connection, since: datetime, before: datetime) -> datetime | None:
    """Frühester Beginn von Dateien, die seit ``since`` registriert wurden und vor ``before``
    liegen (Nachlieferung)."""
    return conn.execute(
        "SELECT min(period_start) FROM raw_files"
        " WHERE status = 'ingested' AND fetched_at >= %s AND period_start < %s",
        (since, before),
    ).fetchone()[0]


def first_position_ts(conn: psycopg.Connection) -> datetime | None:
    return conn.execute("SELECT min(ts) FROM positions").fetchone()[0]


def delete_flights(
    conn: psycopg.Connection, *, last_from: datetime, first_to: datetime | None = None
) -> dict[str, tuple[datetime, datetime]]:
    """Löscht Flüge (samt Ereignissen); liefert je Flugzeug frühesten Beginn und spätestes Ende."""
    rows = conn.execute(
        "DELETE FROM flights WHERE last_ts >= %s"
        " AND (%s::timestamptz IS NULL OR first_ts <= %s) RETURNING icao24, first_ts, last_ts",
        (last_from, first_to, first_to),
    ).fetchall()
    out: dict[str, tuple[datetime, datetime]] = {}
    for icao, first, last in rows:
        lo, hi = out.get(icao, (first, last))
        out[icao] = (min(lo, first), max(hi, last))
    return out


_POINTS = """
SELECT p.icao24, p.ts, ST_Y(p.geom), ST_X(p.geom), p.alt_baro_ft, p.baro_rate_fpm,
       p.callsign, p.on_ground
FROM positions p
LEFT JOIN unnest(%(icaos)s::text[], %(starts)s::timestamptz[], %(ends)s::timestamptz[])
  AS r(icao24, s, e) ON r.icao24 = p.icao24
WHERE p.ts >= %(lo)s AND p.ts <= %(hi)s
  AND p.ts >= coalesce(r.s, %(start)s) AND p.ts <= coalesce(r.e, %(end)s)
ORDER BY p.icao24, p.ts
"""


def aircraft_points(
    conn: psycopg.Connection,
    start: datetime,
    end: datetime,
    ranges: dict[str, tuple[datetime, datetime]],
) -> Iterator[tuple[str, list[Point]]]:
    """Positionen je Flugzeug, zeitlich sortiert; ``ranges`` überschreibt das Zeitfenster
    einzelner Flugzeuge. Bei mehreren Empfängern zählt je Zeitpunkt eine Position."""
    params = {
        "icaos": list(ranges),
        "starts": [r[0] for r in ranges.values()],
        "ends": [r[1] for r in ranges.values()],
        "start": start,
        "end": end,
        "lo": min([start, *(r[0] for r in ranges.values())]),
        "hi": max([end, *(r[1] for r in ranges.values())]),
    }
    with conn.cursor(name="analysis_positions") as cur:
        cur.itersize = 5000
        cur.execute(_POINTS, params)
        for icao, rows in groupby(cur, key=itemgetter(0)):
            points: list[Point] = []
            for _, ts, lat, lon, alt, vrate, callsign, ground in rows:
                if points and points[-1].ts == ts:
                    continue
                points.append(Point(ts, lat, lon, alt, vrate, callsign, ground))
            yield icao, points


def current_zones(conn: psycopg.Connection) -> dict[int, int]:
    return dict(
        conn.execute("SELECT id, relevance_max_alt_ft FROM geofences WHERE valid_to IS NULL")
    )


def insert_flight(conn: psycopg.Connection, run_id: int, seg: Segment) -> int:
    coords = ", ".join(f"{p.lon} {p.lat} {p.ts.timestamp()}" for p in seg.points)
    return conn.execute(
        "INSERT INTO flights (icao24, callsign, first_ts, last_ts, n_positions, n_outliers,"
        " track, analysis_run_id) VALUES (%s, %s, %s, %s, %s, %s, ST_GeomFromEWKT(%s), %s)"
        " RETURNING id",
        (
            seg.icao24,
            seg.callsign,
            seg.first_ts,
            seg.last_ts,
            len(seg.points),
            seg.n_outliers,
            f"SRID=4326;LINESTRING M ({coords})",
            run_id,
        ),
    ).fetchone()[0]


def in_reception_gap(conn: psycopg.Connection, start: datetime, end: datetime) -> bool:
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM reception_gaps WHERE gap_start < %s AND gap_end > %s)",
        (end, start),
    ).fetchone()[0]


_EVENT_COLUMNS = (
    "geofence_id", "entry_ts", "exit_ts", "duration_s", "min_dist_m", "closest_ts",
    "min_alt_ft", "alt_at_closest_ft", "heading_deg", "heading_sector", "category",
    "category_basis", "relevant", "n_positions_inside", "max_position_gap_s", "in_reception_gap",
)


def insert_event(conn: psycopg.Connection, run_id: int, flight_id: int, event: dict) -> None:
    values = event | {"category_basis": Jsonb(event["category_basis"])}
    cols = ", ".join(_EVENT_COLUMNS)
    marks = ", ".join(f"%({c})s" for c in _EVENT_COLUMNS)
    conn.execute(
        f"INSERT INTO overflight_events (flight_id, analysis_run_id, {cols})"
        f" VALUES (%(flight_id)s, %(run_id)s, {marks})",
        values | {"flight_id": flight_id, "run_id": run_id},
    )
```

Hinweis: `ruff format` bricht das Tupel `_EVENT_COLUMNS` in eine Zeile je Eintrag um; das ist in Ordnung.

- [ ] **Step 7: Tests laufen lassen**

Run: `pytest tests/analysis tests/db/test_analysis_events.py -v`
Expected: PASS. Falls `test_straight_crossing_matches_geometry` an der Toleranz scheitert: Ausgabe der Ist-Werte prüfen, **nicht** die Toleranz erhöhen, sondern Ursache klären (Spur-Erzeugung, Kreis-Umrechnung).

- [ ] **Step 8: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/events.py analysis/src/analysis/db.py tests/fixtures/synthetic/tracks.py tests/analysis/test_events.py tests/db/test_analysis_events.py
git commit -m "analysis: Zonendurchquerungen und Kennwerte je Überflug"
```

---

### Task 6: Laufsteuerung `pipeline`

**Files:**
- Create: `analysis/src/analysis/pipeline.py`
- Test: `tests/db/test_analysis_pipeline.py`

**Interfaces:**
- Consumes: alles aus Task 2–5
- Produces:
  - `SchemaMissing(RuntimeError)`, `NoZones(RuntimeError)`
  - `RunResult(run_id: int, kind: str, window_from: datetime, window_to: datetime, flights: int, events: int, skipped: int)`
  - `compute_window(conn, cfg) -> tuple[datetime, datetime] | None`
  - `run_once(cfg) -> RunResult | None`
  - `rebuild(cfg, start: datetime, end: datetime) -> RunResult | None`
  - `sync_zones(cfg, path: Path) -> ZoneSync`

- [ ] **Step 1: Tests schreiben** – `tests/db/test_analysis_pipeline.py`:

```python
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from analysis.config import Config
from analysis.pipeline import NoZones, compute_window, rebuild, run_once, sync_zones
from synthetic.tracks import add_raw_file, insert_positions, offset, straight

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)
ZONES = (
    '{"type": "FeatureCollection", "features": [{"type": "Feature", "geometry":'
    ' {"type": "Point", "coordinates": [10.0, 50.0]}, "properties": {"name": "Testzone",'
    ' "radius_m": 5000}}]}'
)


@pytest.fixture
def cfg(db_dsns, tmp_path):
    zones = tmp_path / "geofences.geojson"
    zones.write_text(ZONES, encoding="utf-8")
    c = Config(db_dsn=db_dsns["analysis"], ber_lat=49.0, ber_lon=8.0, zones_file=zones)
    sync_zones(c, zones)
    return c


def east_track(start=T0, icao="ff0001", n=400):
    lat, lon = offset(50.0, 10.0, 2000, -20000)
    return straight(start, lat, lon, 90, 200, n, icao24=icao)


def q(dsn, sql):
    with psycopg.connect(dsn) as c:
        return c.execute(sql).fetchall()


def test_first_run_builds_flight_and_event(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))

    result = run_once(cfg)

    assert (result.kind, result.flights, result.events, result.skipped) == ("incremental", 1, 1, 0)
    assert result.window_to == T0 + timedelta(hours=1) - timedelta(seconds=120)
    (row,) = q(
        db_dsns["reader"],
        "SELECT category, relevant, heading_sector, in_reception_gap, round(duration_s)"
        " FROM overflight_events",
    )
    assert row == ("overflight", True, "O", False, 89)
    assert q(db_dsns["reader"], "SELECT status, kind FROM analysis_runs") == [
        ("ok", "incremental")
    ]


def test_nothing_new_creates_no_run(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    run_once(cfg)
    assert run_once(cfg) is None
    assert len(q(db_dsns["reader"], "SELECT id FROM analysis_runs")) == 1


def test_open_flight_is_extended_without_duplicates(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(minutes=5))  # Fenster bis 180 s
    first = run_once(cfg)
    assert first.window_to == T0 + timedelta(seconds=180)
    add_raw_file(db_dsns["admin"], T0 + timedelta(minutes=5), T0 + timedelta(minutes=10))

    run_once(cfg)

    assert q(db_dsns["reader"], "SELECT count(*) FROM flights") == [(1,)]
    ((n, exit_s),) = q(
        db_dsns["reader"],
        "SELECT count(*), round(extract(epoch FROM max(exit_ts) - '2026-11-09T14:00:00Z'))"
        " FROM overflight_events",
    )
    assert (n, exit_s) == (1, 239)


def test_late_file_triggers_recompute(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track(T0 + timedelta(hours=1), icao="ff0001"))
    add_raw_file(db_dsns["admin"], T0 + timedelta(hours=1), T0 + timedelta(hours=2))
    run_once(cfg)

    insert_positions(db_dsns["admin"], east_track(T0 + timedelta(minutes=10), icao="ff0002"))
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    result = run_once(cfg)

    assert result.window_from == T0 - timedelta(seconds=120)
    assert q(db_dsns["reader"], "SELECT icao24, count(*) FROM flights GROUP BY 1 ORDER BY 1") == [
        ("ff0001", 1),
        ("ff0002", 1),
    ]


def test_pending_file_caps_window(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    add_raw_file(db_dsns["admin"], T0 + timedelta(minutes=30), T0, status="registered")
    with psycopg.connect(cfg.db_dsn) as c:
        _, window_to = compute_window(c, cfg)
    assert window_to == T0 + timedelta(minutes=30) - timedelta(seconds=120)


def test_rebuild_reproduces_events(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    run_once(cfg)
    sql = (
        "SELECT f.icao24, e.entry_ts, e.exit_ts, round(e.min_dist_m), e.category"
        " FROM overflight_events e JOIN flights f ON f.id = e.flight_id ORDER BY 1, 2"
    )
    before = q(db_dsns["reader"], sql)

    result = rebuild(cfg, T0 - timedelta(days=1), T0 + timedelta(days=1))

    assert result.kind == "rebuild" and result.events == 1
    assert q(db_dsns["reader"], sql) == before
    assert q(db_dsns["reader"], "SELECT count(*) FROM flights") == [(1,)]


def test_missing_zones_marks_run_failed(db_dsns, cfg):
    insert_positions(db_dsns["admin"], east_track())
    add_raw_file(db_dsns["admin"], T0, T0 + timedelta(hours=1))
    with psycopg.connect(db_dsns["admin"], autocommit=True) as c:
        c.execute("UPDATE geofences SET valid_to = now()")

    with pytest.raises(NoZones):
        run_once(cfg)

    ((status, error),) = q(db_dsns["reader"], "SELECT status, error FROM analysis_runs")
    assert status == "failed" and "Zone" in error
    assert q(db_dsns["reader"], "SELECT count(*) FROM flights") == [(0,)]
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/db/test_analysis_pipeline.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'analysis.pipeline'`.

- [ ] **Step 3: Implementierung** – `analysis/src/analysis/pipeline.py`:

```python
"""Laufsteuerung: Zeitfenster bestimmen, Flüge und Überflüge neu bilden, protokollieren."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

from analysis import __version__, db, events
from analysis.config import Config
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


def compute_window(conn: psycopg.Connection, cfg: Config) -> tuple[datetime, datetime] | None:
    end = db.data_end(conn)
    if end is None:
        return None
    settle = timedelta(seconds=cfg.settle_s)
    window_to = end - settle
    pending = db.pending_starts(conn)
    if pending:
        window_to = min(window_to, min(pending) - settle)

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


def _aircraft(
    conn: psycopg.Connection,
    cfg: Config,
    run_id: int,
    icao: str,
    points: list[Point],
    zones: dict[int, int],
) -> tuple[int, int]:
    n_flights = n_events = 0
    for seg in segment(icao, points, gap_s=cfg.flight_gap_s, max_speed_kt=cfg.max_speed_kt):
        flight_id = db.insert_flight(conn, run_id, seg)
        n_flights += 1
        for c in events.crossings(conn, flight_id):
            event = events.build_event(c, seg.points, zones[c.geofence_id], cfg)
            event["in_reception_gap"] = db.in_reception_gap(conn, c.entry, c.exit)
            db.insert_event(conn, run_id, flight_id, event)
            n_events += 1
    return n_flights, n_events


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
    # Gelöschte Flüge werden ab ihrem Beginn neu gebildet, aber nur für ihr Flugzeug.
    ranges = {icao: (min(start, first), max(end, last)) for icao, (first, last) in deleted.items()}
    counts = db.Counts()
    for icao, points in db.aircraft_points(conn, start, end, ranges):
        try:
            with conn.transaction():
                n_flights, n_events = _aircraft(conn, cfg, run_id, icao, points, zones)
        except psycopg.OperationalError:
            raise
        except psycopg.Error as e:
            counts.skipped += 1
            log.warning("Flugzeug übersprungen", extra={"icao24": icao, "error": str(e)})
            continue
        counts.flights += n_flights
        counts.events += n_events
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
    return RunResult(run_id, kind, start, end, counts.flights, counts.events, counts.skipped)


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
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/db/test_analysis_pipeline.py -v`
Expected: PASS. `test_open_flight_is_extended_without_duplicates` erwartet den Austritt bei 239 s (238,92 s gerundet).

- [ ] **Step 5: Gesamte Suite**

Run: `pytest`
Expected: alle PASS.

- [ ] **Step 6: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/src/analysis/pipeline.py tests/db/test_analysis_pipeline.py
git commit -m "analysis: inkrementelle Läufe, Nachlieferung und Neuberechnung"
```

---

### Task 7: Kommandozeile, Container und NAS-Stack

**Files:**
- Create: `analysis/src/analysis/cli.py`, `analysis/src/analysis/__main__.py`, `analysis/Dockerfile`
- Modify: `nas/docker-compose.yml`, `nas/.env.example`
- Test: `tests/analysis/test_analysis_cli.py`

**Interfaces:**
- Consumes: `run_once`, `rebuild`, `sync_zones`, `SchemaMissing` (Task 6), `Config` (Task 2)
- Produces: `python -m analysis {run|once|rebuild --from JJJJ-MM-TT --to JJJJ-MM-TT|zones [datei]|health}`; `cli.main(argv) -> int`

- [ ] **Step 1: Tests schreiben** – `tests/analysis/test_analysis_cli.py`:

```python
import os
import time

import pytest
from analysis import cli

ENV = {"ANALYSIS_DB_DSN": "postgresql://u@127.0.0.1:1/x", "ANALYSIS_BER_LAT": "49",
       "ANALYSIS_BER_LON": "8"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ANALYSIS_ZONES_FILE", raising=False)
    hb = tmp_path / "hb"
    monkeypatch.setenv("ANALYSIS_HEARTBEAT_FILE", str(hb))
    monkeypatch.setenv("ANALYSIS_INTERVAL_S", "10")
    return hb


def test_health_without_heartbeat_fails(env):
    assert cli.main(["health"]) == 1


def test_health_with_stale_heartbeat_fails(env):
    env.write_text("")
    old = time.time() - 60
    os.utime(env, (old, old))
    assert cli.main(["health"]) == 1


def test_health_fresh_heartbeat_but_db_unreachable_fails(env):
    env.write_text("")
    assert cli.main(["health"]) == 1


def test_zones_without_file_is_error(env):
    assert cli.main(["zones"]) == 2
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_analysis_cli.py -v`
Expected: FAIL mit `ImportError: cannot import name 'cli'`.

- [ ] **Step 3: Implementierung**

`analysis/src/analysis/cli.py`:

```python
"""Kommandozeile: ``python -m analysis {run|once|rebuild|zones|health}``."""

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
from analysis.pipeline import rebuild, run_once, sync_zones

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
    except psycopg.Error:
        return 1
    return 1 if row and row[0] == "failed" else 0


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
            },
        )


def _iteration(cfg: Config) -> None:
    if cfg.zones_file is not None:
        sync_zones(cfg, cfg.zones_file)
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

`analysis/src/analysis/__main__.py`:

```python
import sys

from analysis.cli import main

sys.exit(main())
```

`analysis/Dockerfile`:

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir "psycopg[binary]==3.2.3" \
 && useradd -u 1000 -m analysis

WORKDIR /app
COPY analysis/src/ /app/
ENV PYTHONUNBUFFERED=1

USER analysis
HEALTHCHECK --interval=60s --timeout=15s --start-period=180s --retries=3 \
  CMD ["python", "-m", "analysis", "health"]
CMD ["python", "-m", "analysis", "run"]
```

- [ ] **Step 4: NAS-Stack** – in `nas/docker-compose.yml` nach dem Dienst `ingest` einfügen:

```yaml
  analysis:
    build:
      context: ..
      dockerfile: analysis/Dockerfile
    restart: unless-stopped
    depends_on:
      postgis:
        condition: service_healthy
    environment:
      ANALYSIS_DB_DSN: postgresql://flightdb_analysis:${DB_ANALYSIS_PASSWORD}@postgis:5432/${POSTGRES_DB}
      ANALYSIS_INTERVAL_S: ${ANALYSIS_INTERVAL_S:-300}
      ANALYSIS_BER_LAT: ${ANALYSIS_BER_LAT}
      ANALYSIS_BER_LON: ${ANALYSIS_BER_LON}
      ANALYSIS_ZONES_FILE: /zones/geofences.geojson
    volumes:
      # Verzeichnis statt Datei: fehlt die Datei, legt Docker sonst einen leeren Ordner an.
      - ${ZONES_DIR:-../config/local}:/zones:ro
    logging: *logging
```

In `nas/.env.example` nach dem Block `# --- Empfangsstation ---` einfügen:

```bash
# --- Analyse ---
ANALYSIS_INTERVAL_S=300
# Flughafen-Referenzpunkt BER (öffentlich, AIP) – Grundlage der Anflug/Abflug-Heuristik
ANALYSIS_BER_LAT=52.3622
ANALYSIS_BER_LON=13.5006
# Ordner mit geofences.geojson (Standard: config/local im Repo, gitignored)
ZONES_DIR=../config/local
```

- [ ] **Step 5: Tests und Build**

Run: `pytest tests/analysis -v && docker build -f analysis/Dockerfile -t flightdb-analysis:test . && docker compose -f nas/docker-compose.yml --env-file nas/.env.example config -q`
Expected: Tests PASS, Image baut, Compose-Datei gültig.

- [ ] **Step 6: Lint und Commit**

```bash
ruff format . && ruff check .
git add analysis/ nas/ tests/analysis/test_analysis_cli.py
git commit -m "analysis: Kommandozeile, Container und NAS-Stack"
```

---

### Task 8: Grafana – Dashboards, Provisioning, Prüfskript

**Files:**
- Create: `dashboard/build_dashboards.py`, `dashboard/dashboards/ueberfluege.json`, `dashboard/dashboards/datenqualitaet.json`, `dashboard/dashboards/flugspur.json` (generiert), `dashboard/provisioning/datasources/flightdb.yaml`, `dashboard/provisioning/dashboards/flightdb.yaml`, `scripts/check_dashboards.py`, `tests/fixtures/dashboard_sql.py`
- Modify: `nas/docker-compose.yml`, `nas/.env.example`, `.github/workflows/ci.yml`
- Test: `tests/analysis/test_dashboards.py`, `tests/db/test_dashboard_queries.py`

**Interfaces:**
- Produces:
  - `build_dashboards.build() -> dict[str, dict]` (Dateiname → Dashboard), `build_dashboards.write(out: Path = OUT) -> None`, `build_dashboards.queries(dashboard: dict) -> list[str]` (alle SQL-Texte aus Panels und Variablen)
  - `check_dashboards.problems(obj, path="$") -> list[str]`, `check_dashboards.main(argv) -> int`
  - `dashboard_sql.substitute(sql: str, *, macros: bool = True) -> str`

- [ ] **Step 1: Test-Hilfe** – `tests/fixtures/dashboard_sql.py`:

```python
"""Ersetzt Grafana-Variablen (und optional Makros) in Panel-SQL für Tests."""

from __future__ import annotations

import re

VARIABLES = [
    (r"\(\$zone\)", "('Testzone')"),
    (r"\(\$category\)", "('arrival', 'departure', 'overflight', 'unknown')"),
    (r"'\$relevant'", "'alle'"),
    (r"'\$bucket'", "'day'"),
    (r"\$flight_id\b", "0"),
]
MACROS = [
    (r"\$__timeFilter\(([^)]+)\)", r"\1 BETWEEN '2026-01-01T00:00:00Z' AND '2027-01-01T00:00:00Z'"),
    (r"\$__timeFrom\(\)", "'2026-01-01T00:00:00Z'"),
    (r"\$__timeTo\(\)", "'2027-01-01T00:00:00Z'"),
]


def substitute(sql: str, *, macros: bool = True) -> str:
    for pattern, repl in VARIABLES + (MACROS if macros else []):
        sql = re.sub(pattern, repl, sql)
    return sql
```

- [ ] **Step 2: Tests schreiben** – `tests/analysis/test_dashboards.py`:

```python
import json
from pathlib import Path

import build_dashboards
import check_dashboards

ROOT = Path(__file__).resolve().parents[2]


def test_generated_files_are_current():
    for name, dashboard in build_dashboards.build().items():
        on_disk = json.loads((ROOT / "dashboard" / "dashboards" / name).read_text("utf-8"))
        assert on_disk == dashboard, f"{name} veraltet – python dashboard/build_dashboards.py"


def test_dashboards_have_unique_uids_and_panel_ids():
    dashboards = build_dashboards.build().values()
    assert len({d["uid"] for d in dashboards}) == 3
    for d in dashboards:
        ids = [p["id"] for p in d["panels"]]
        assert len(ids) == len(set(ids))


def test_repo_dashboards_contain_no_locations():
    files = sorted((ROOT / "dashboard" / "dashboards").glob("*.json"))
    assert files and check_dashboards.main([str(f) for f in files]) == 0


def test_checker_finds_map_center_and_zoom():
    bad = {
        "panels": [
            {"type": "geomap", "options": {"view": {"id": "coords", "lat": 45.0, "lon": -30.0,
                                                    "zoom": 11}}}
        ]
    }
    found = check_dashboards.problems(bad)
    assert len(found) == 4  # Ansicht nicht 'fit', lat, lon, zoom


def test_checker_accepts_field_names():
    ok = {"type": "geomap", "options": {"view": {"id": "fit"}, "layers": [
        {"location": {"mode": "coords", "latitude": "latitude", "longitude": "longitude"}}]}}
    assert check_dashboards.problems(ok) == []
```

`tests/db/test_dashboard_queries.py`:

```python
import build_dashboards
import psycopg
import pytest
from dashboard_sql import substitute

pytestmark = pytest.mark.db


@pytest.mark.parametrize("name", sorted(build_dashboards.build()))
def test_all_queries_run_as_reader(db_dsns, name):
    dashboard = build_dashboards.build()[name]
    with psycopg.connect(db_dsns["reader"]) as c:
        for sql in build_dashboards.queries(dashboard):
            final = substitute(sql)
            assert "$" not in final, final
            c.execute(final)
            c.rollback()
```

- [ ] **Step 3: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_dashboards.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'build_dashboards'`.

- [ ] **Step 4: Prüfskript** – `scripts/check_dashboards.py`:

```python
#!/usr/bin/env python3
"""Prüft Grafana-Dashboards auf Ortsangaben (öffentliches Repo).

Karten müssen die Ansicht „Fit to data“ (``view.id == "fit"``) nutzen; Zahlenwerte unter
Schlüsseln wie lat/lon/zoom/center sind verboten. Feldnamen (Zeichenketten) sind erlaubt.
Aufruf: python scripts/check_dashboards.py dashboard/dashboards/*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FORBIDDEN = {"lat", "lon", "lng", "latitude", "longitude", "zoom", "center"}


def problems(obj, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        if obj.get("type") == "geomap":
            view = (obj.get("options") or {}).get("view") or {}
            if view.get("id") != "fit":
                found.append(f"{path}: Kartenansicht muss 'fit' sein")
        for key, value in obj.items():
            if key.lower() in FORBIDDEN and not isinstance(value, str | bool):
                found.append(f"{path}.{key}: Koordinaten oder Zoom nicht erlaubt")
            found += problems(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found += problems(value, f"{path}[{i}]")
    return found


def main(argv: list[str]) -> int:
    failed = 0
    for name in argv:
        for problem in problems(json.loads(Path(name).read_text(encoding="utf-8"))):
            print(f"{name}: {problem}", file=sys.stderr)
            failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Dashboard-Generator** – `dashboard/build_dashboards.py`:

```python
#!/usr/bin/env python3
"""Erzeugt die Grafana-Dashboards: ``python dashboard/build_dashboards.py``.

Die JSON-Dateien in ``dashboard/dashboards/`` sind generiert und werden mit committet
(ein Test prüft, dass sie aktuell sind). Keine Koordinaten, Kartenmittelpunkte oder
Zoomstufen eintragen – Karten nutzen „Fit to data“ (siehe scripts/check_dashboards.py).
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "flightdb"}
TZ = "'Europe/Berlin'"

EVENT_FILTER = """
  e.geofence_id IN (SELECT id FROM geofences WHERE name IN ($zone))
  AND e.category IN ($category)
  AND (e.relevant OR '$relevant' = 'alle')"""

SECTOR_ORDER = "array_position(ARRAY['N','NO','O','SO','S','SW','W','NW'], e.heading_sector)"
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# --- Bausteine --------------------------------------------------------------------------


def target(sql: str, fmt: str = "table", ref: str = "A") -> dict:
    return {
        "refId": ref,
        "datasource": DS,
        "editorMode": "code",
        "format": fmt,
        "rawQuery": True,
        "rawSql": sql.strip(),
    }


def panel(kind: str, title: str, grid: tuple[int, int, int, int], targets: list[dict], **extra):
    x, y, w, h = grid
    p = {
        "type": kind,
        "title": title,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
    }
    for key, value in extra.items():
        p[key] = value
    return p


def stat(title, sql, grid, unit="none"):
    return panel(
        "stat", title, grid, [target(sql)],
        fieldConfig={"defaults": {"unit": unit}, "overrides": []},
        options={"reduceOptions": {"calcs": ["lastNotNull"], "values": False}},
    )


def query_var(name, label, sql, multi=True):
    return {
        "type": "query", "name": name, "label": label, "datasource": DS,
        "query": sql, "definition": sql, "refresh": 1, "multi": multi, "includeAll": multi,
        "current": {"text": "All", "value": "$__all"} if multi else {},
    }


def custom_var(name, label, values, default, multi=False, include_all=False):
    current = (
        {"text": "All", "value": "$__all"} if include_all else {"text": default, "value": default}
    )
    return {
        "type": "custom", "name": name, "label": label, "query": ",".join(values),
        "multi": multi, "includeAll": include_all, "current": current,
        "options": [{"text": v, "value": v, "selected": v == default} for v in values],
    }


def textbox_var(name, label, default=""):
    return {"type": "textbox", "name": name, "label": label, "query": default,
            "current": {"text": default, "value": default}}


def dashboard(uid, title, panels, variables, links=(), time_from="now-7d"):
    for i, p in enumerate(panels, start=1):
        p["id"] = i
    return {
        "uid": uid,
        "title": title,
        "tags": ["flightdb"],
        "timezone": "browser",
        "schemaVersion": 39,
        "editable": True,
        "time": {"from": time_from, "to": "now"},
        "templating": {"list": variables},
        "links": list(links),
        "panels": panels,
    }


def queries(d: dict) -> list[str]:
    out = [t["rawSql"] for p in d["panels"] for t in p.get("targets", [])]
    out += [v["query"] for v in d["templating"]["list"] if v["type"] == "query"]
    return out


# --- Dashboard „Überflüge“ --------------------------------------------------------------


def _count_since(since_sql: str) -> str:
    return (
        f"SELECT count(*) AS n FROM overflight_events e WHERE {EVENT_FILTER}\n"
        f"  AND e.entry_ts >= {since_sql}"
    )


def _hour_weekday_sql() -> str:
    hours = ",\n  ".join(
        f"count(*) FILTER (WHERE extract(hour FROM e.entry_ts AT TIME ZONE {TZ}) = {h})"
        f' AS "{h:02d}"'
        for h in range(24)
    )
    names = ", ".join(f"'{d}'" for d in WEEKDAYS)
    return f"""
SELECT (ARRAY[{names}])[extract(isodow FROM e.entry_ts AT TIME ZONE {TZ})::int] AS "Tag",
  {hours}
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
GROUP BY extract(isodow FROM e.entry_ts AT TIME ZONE {TZ})
ORDER BY extract(isodow FROM e.entry_ts AT TIME ZONE {TZ})"""


def ueberfluege() -> dict:
    today = f"date_trunc('day', now() AT TIME ZONE {TZ}) AT TIME ZONE {TZ}"
    series = f"""
SELECT date_trunc('$bucket', e.entry_ts AT TIME ZONE {TZ}) AT TIME ZONE {TZ} AS time,
  e.category AS metric, count(*) AS value
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
GROUP BY 1, 2 ORDER BY 1"""
    heights = f"""
SELECT to_char(floor(e.min_alt_ft / 1000.0) * 1000, 'FM99990') AS "ab ft", count(*) AS n
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER} AND e.min_alt_ft IS NOT NULL
GROUP BY floor(e.min_alt_ft / 1000.0) ORDER BY floor(e.min_alt_ft / 1000.0)"""
    sectors = f"""
SELECT e.heading_sector AS "Richtung", count(*) AS n
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER} AND e.heading_sector IS NOT NULL
GROUP BY e.heading_sector ORDER BY min({SECTOR_ORDER})"""
    categories = f"""
SELECT e.category AS "Kategorie", count(*) AS n
FROM overflight_events e
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
GROUP BY 1 ORDER BY 1"""
    lowest = f"""
SELECT e.entry_ts AS "Zeit", f.callsign AS "Rufzeichen", f.icao24 AS "ICAO24",
  e.min_alt_ft AS "Höhe ft", round(e.min_dist_m) AS "Abstand m", e.category AS "Kategorie",
  g.name AS "Zone", e.n_positions_inside AS "Positionen",
  round(e.max_position_gap_s) AS "max. Lücke s",
  e.in_reception_gap AS "Empfangslücke", e.flight_id,
  (extract(epoch FROM f.first_ts) * 1000)::bigint AS t_from,
  (extract(epoch FROM f.last_ts) * 1000)::bigint AS t_to
FROM overflight_events e
JOIN flights f ON f.id = e.flight_id
JOIN geofences g ON g.id = e.geofence_id
WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
ORDER BY e.min_alt_ft NULLS LAST LIMIT 50"""
    heat = f"""
WITH ev AS (
  SELECT DISTINCT e.flight_id FROM overflight_events e
  WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}
)
SELECT round(ST_Y(d.geom)::numeric, 3)::float AS latitude,
  round(ST_X(d.geom)::numeric, 3)::float AS longitude, count(*) AS n
FROM flights f JOIN ev ON ev.flight_id = f.id, LATERAL ST_DumpPoints(f.track) d
GROUP BY 1, 2"""
    zone_outline = """
SELECT g.name AS zone, ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude
FROM geofences g, LATERAL ST_DumpPoints(g.geom) d
WHERE g.valid_to IS NULL AND g.name IN ($zone)"""
    coverage = """
SELECT 100 * sum(greatest(recorded_s - gap_s, 0)) / nullif(sum(day_s), 0) AS "%"
FROM data_coverage_daily
WHERE day BETWEEN ($__timeFrom())::timestamptz::date AND ($__timeTo())::timestamptz::date"""

    track_link = {
        "title": "Flugspur",
        "url": "/d/flightdb-flugspur/flugspur?var-flight_id=${__data.fields.flight_id}"
        "&from=${__data.fields.t_from}&to=${__data.fields.t_to}",
    }
    hidden = [
        {"matcher": {"id": "byName", "options": n},
         "properties": [{"id": "custom.hidden", "value": True}]}
        for n in ("flight_id", "t_from", "t_to")
    ]
    panels = [
        stat("Überflüge heute", _count_since(today), (0, 0, 4, 4)),
        stat("Überflüge 7 Tage", _count_since("now() - interval '7 days'"), (4, 0, 4, 4)),
        stat("Überflüge 30 Tage", _count_since("now() - interval '30 days'"), (8, 0, 4, 4)),
        stat(
            "Niedrigste Höhe im Zeitraum",
            f"SELECT min(e.min_alt_ft) AS ft FROM overflight_events e"
            f" WHERE $__timeFilter(e.entry_ts) AND {EVENT_FILTER}",
            (12, 0, 6, 4),
            unit="lengthft",
        ),
        stat("Empfangsabdeckung im Zeitraum", coverage, (18, 0, 6, 4), unit="percent"),
        panel(
            "timeseries", "Überflüge je Intervall (nach Kategorie)", (0, 4, 24, 8),
            [target(series, "time_series")],
            fieldConfig={"defaults": {"custom": {"drawStyle": "bars", "fillOpacity": 80,
                                                 "stacking": {"mode": "normal"}}},
                         "overrides": []},
        ),
        panel(
            "table", "Tageszeit × Wochentag", (0, 12, 24, 7), [target(_hour_weekday_sql())],
            fieldConfig={"defaults": {"custom": {"cellOptions": {"type": "color-background"}},
                                      "color": {"mode": "continuous-YlRd"}},
                         "overrides": []},
        ),
        panel("barchart", "Höhenverteilung (niedrigste Höhe je Überflug)", (0, 19, 8, 8),
              [target(heights)], options={"xField": "ab ft"}),
        panel("barchart", "Flugrichtung", (8, 19, 8, 8), [target(sectors)],
              options={"xField": "Richtung"}),
        panel("piechart", "Kategorien (heuristisch)", (16, 19, 8, 8), [target(categories)],
              description="Anflug/Abflug ist eine Näherung aus Höhenverlauf und Abstand zu BER,"
              " keine Verfahrenszuordnung.",
              options={"reduceOptions": {"values": True, "calcs": []}}),
        panel(
            "table", "Tiefste Überflüge", (0, 27, 24, 10), [target(lowest)],
            fieldConfig={"defaults": {}, "overrides": hidden + [
                {"matcher": {"id": "byName", "options": "Rufzeichen"},
                 "properties": [{"id": "links", "value": [track_link]}]}
            ]},
        ),
        panel(
            "geomap", "Spuren und Zonen", (0, 37, 24, 14),
            [target(heat, ref="A"), target(zone_outline, ref="B")],
            options={
                "view": {"id": "fit", "allLayers": True, "padding": 5},
                "controls": {"showZoom": True, "mouseWheelZoom": True},
                "basemap": {"type": "default", "name": "Karte"},
                "layers": [
                    {"type": "heatmap", "name": "Spuren",
                     "filterData": {"id": "byRefId", "options": "A"},
                     "location": {"mode": "coords", "latitude": "latitude",
                                  "longitude": "longitude"},
                     "config": {"blur": 15, "radius": 4,
                                "weight": {"field": "n", "fixed": 1, "min": 0, "max": 1}}},
                    {"type": "markers", "name": "Zonen",
                     "filterData": {"id": "byRefId", "options": "B"},
                     "location": {"mode": "coords", "latitude": "latitude",
                                  "longitude": "longitude"},
                     "config": {"style": {"size": {"fixed": 2},
                                          "color": {"fixed": "dark-red"}}}},
                ],
            },
        ),
    ]
    variables = [
        query_var("zone", "Zone",
                  "SELECT name FROM geofences WHERE valid_to IS NULL ORDER BY name"),
        custom_var("category", "Kategorie", ["arrival", "departure", "overflight", "unknown"],
                   "arrival", multi=True, include_all=True),
        custom_var("relevant", "Überflüge", ["relevante", "alle"], "relevante"),
        custom_var("bucket", "Intervall", ["hour", "day", "week", "month"], "day"),
    ]
    return dashboard("flightdb-ueberfluege", "Überflüge", panels, variables)


# --- Dashboard „Datenqualität“ ----------------------------------------------------------


def datenqualitaet() -> dict:
    panels = [
        panel("timeseries", "Empfangsabdeckung je Tag", (0, 0, 12, 8), [target(f"""
SELECT day::timestamp AT TIME ZONE {TZ} AS time, receiver_id AS metric,
  100 * greatest(recorded_s - gap_s, 0) / nullif(day_s, 0) AS value
FROM data_coverage_daily
WHERE day BETWEEN ($__timeFrom())::timestamptz::date AND ($__timeTo())::timestamptz::date
ORDER BY 1""", "time_series")], fieldConfig={"defaults": {"unit": "percent", "max": 100},
                                             "overrides": []}),
        panel("timeseries", "Positionen je Stunde", (12, 0, 12, 8), [target("""
SELECT date_trunc('hour', ts) AS time, count(*) AS value
FROM positions WHERE $__timeFilter(ts)
GROUP BY 1 ORDER BY 1""", "time_series")]),
        panel("timeseries", "Dateien je Stunde", (0, 8, 12, 8), [target("""
SELECT date_trunc('hour', period_start) AS time, status AS metric, count(*) AS value
FROM raw_files WHERE $__timeFilter(period_start)
GROUP BY 1, 2 ORDER BY 1""", "time_series")]),
        panel("timeseries", "Uhrabweichung (max. je Datei)", (12, 8, 12, 8), [target("""
SELECT period_start AS time, clock_offset_max_s AS value
FROM raw_files WHERE $__timeFilter(period_start) AND clock_offset_max_s IS NOT NULL
ORDER BY 1""", "time_series")], fieldConfig={"defaults": {"unit": "s"}, "overrides": []}),
        panel("table", "Empfangslücken", (0, 16, 12, 9), [target("""
SELECT gap_start AS "Beginn", gap_end AS "Ende",
  round(extract(epoch FROM gap_end - gap_start)) AS "Dauer s", reason AS "Grund"
FROM reception_gaps WHERE $__timeFilter(gap_start)
ORDER BY gap_start DESC LIMIT 200""")]),
        panel("table", "Ingest-Status", (12, 16, 12, 4), [target("SELECT * FROM ingest_status")]),
        panel("table", "Analyse-Läufe", (12, 20, 12, 9), [target("""
SELECT id, kind AS "Art", status, started_at AS "Beginn", finished_at AS "Ende",
  window_from AS "von", window_to AS "bis", n_flights AS "Flüge", n_events AS "Überflüge",
  n_skipped AS "übersprungen", error AS "Fehler"
FROM analysis_runs ORDER BY id DESC LIMIT 20""")]),
    ]
    variables = [textbox_var("tar1090", "tar1090-Adresse (lokal setzen)")]
    links = [{"title": "Live-Karte (tar1090)", "type": "link", "url": "${tar1090}",
              "targetBlank": True}]
    return dashboard("flightdb-datenqualitaet", "Datenqualität", panels, variables, links,
                     time_from="now-2d")


# --- Dashboard „Flugspur“ ---------------------------------------------------------------


def flugspur() -> dict:
    panels = [
        panel("geomap", "Spur", (0, 0, 14, 14), [target("""
SELECT ST_Y(d.geom) AS latitude, ST_X(d.geom) AS longitude,
  to_timestamp(ST_M(d.geom)) AS time
FROM flights f, LATERAL ST_DumpPoints(f.track) d
WHERE f.id = $flight_id ORDER BY d.path""")], options={
            "view": {"id": "fit", "allLayers": True, "padding": 10},
            "controls": {"showZoom": True, "mouseWheelZoom": True},
            "basemap": {"type": "default", "name": "Karte"},
            "layers": [{"type": "markers", "name": "Spur",
                        "location": {"mode": "coords", "latitude": "latitude",
                                     "longitude": "longitude"},
                        "config": {"style": {"size": {"fixed": 3},
                                             "color": {"fixed": "blue"}}}}],
        }),
        panel("table", "Überflüge dieses Flugs", (14, 0, 10, 14), [target("""
SELECT g.name AS "Zone", e.entry_ts AS "Eintritt", e.exit_ts AS "Austritt",
  e.min_alt_ft AS "Höhe ft", round(e.min_dist_m) AS "Abstand m", e.heading_sector AS "Richtung",
  e.category AS "Kategorie", e.category_basis::text AS "Begründung"
FROM overflight_events e JOIN geofences g ON g.id = e.geofence_id
WHERE e.flight_id = $flight_id ORDER BY e.entry_ts""")]),
        panel("timeseries", "Höhe und Geschwindigkeit", (0, 14, 24, 9), [target("""
SELECT p.ts AS time, p.alt_baro_ft AS "Höhe ft", p.gs_kt AS "Geschwindigkeit kt"
FROM positions p JOIN flights f ON p.icao24 = f.icao24
  AND p.ts BETWEEN f.first_ts AND f.last_ts
WHERE f.id = $flight_id ORDER BY 1""", "time_series")]),
    ]
    variables = [textbox_var("flight_id", "Flug-ID", "0")]
    return dashboard("flightdb-flugspur", "Flugspur", panels, variables, time_from="now-24h")


def build() -> dict[str, dict]:
    return {
        "ueberfluege.json": ueberfluege(),
        "datenqualitaet.json": datenqualitaet(),
        "flugspur.json": flugspur(),
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

`ruff format .` bricht lange Code-Zeilen um; SQL-Zeichenketten sind bereits unter 100 Zeichen.

- [ ] **Step 6: JSON erzeugen**

Run: `python dashboard/build_dashboards.py && python scripts/check_dashboards.py dashboard/dashboards/*.json`
Expected: drei Dateien in `dashboard/dashboards/`, Prüfskript ohne Ausgabe, Exit-Code 0.

- [ ] **Step 7: Provisioning** – `dashboard/provisioning/datasources/flightdb.yaml`:

```yaml
# Grafana liest nur über die Rolle flightdb_reader; Werte kommen aus der Container-Umgebung.
apiVersion: 1
datasources:
  - name: flightdb
    uid: flightdb
    type: grafana-postgresql-datasource
    access: proxy
    url: postgis:5432
    user: flightdb_reader
    isDefault: true
    jsonData:
      database: ${POSTGRES_DB}
      sslmode: disable
      postgresVersion: 1600
      timescaledb: false
    secureJsonData:
      password: ${DB_READONLY_PASSWORD}
```

`dashboard/provisioning/dashboards/flightdb.yaml`:

```yaml
# Dashboards aus dem Repo. Änderungen in der Oberfläche (z. B. tar1090-Adresse) bleiben in der
# Grafana-Datenbank, bis sich die Datei im Repo ändert.
apiVersion: 1
providers:
  - name: flightdb
    folder: flightdb
    type: file
    allowUiUpdates: true
    options:
      path: /etc/grafana/dashboards
```

- [ ] **Step 8: NAS-Stack** – in `nas/docker-compose.yml` vor `backup:` einfügen:

```yaml
  grafana:
    image: grafana/grafana:13.2.6@sha256:b21409d7951ddcfd63a4b49083e4ef2cc35bc1437d071813bf82bfb238b00bca
    restart: unless-stopped
    depends_on:
      postgis:
        condition: service_healthy
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
      GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES: "false"
      GF_NEWS_NEWS_FEED_ENABLED: "false"
      GF_DATE_FORMATS_DEFAULT_TIMEZONE: Europe/Berlin
      POSTGRES_DB: ${POSTGRES_DB}
      DB_READONLY_PASSWORD: ${DB_READONLY_PASSWORD}
    volumes:
      - ${GRAFANA_DATA_DIR}:/var/lib/grafana
      - ../dashboard/provisioning:/etc/grafana/provisioning:ro
      - ../dashboard/dashboards:/etc/grafana/dashboards:ro
    ports:
      - "${GRAFANA_LAN_PORT:-3001}:3000"
    healthcheck:
      test: ["CMD", "wget", "-q", "-O-", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 5
    logging: *logging
```

In `nas/.env.example` anhängen:

```bash
# --- Grafana (nur LAN) ---
GRAFANA_ADMIN_PASSWORD=change-me
GRAFANA_DATA_DIR=/volumeX/docker/flightdb/grafana
GRAFANA_LAN_PORT=3001
```

- [ ] **Step 9: CI** – in `.github/workflows/ci.yml` im Job `test` nach `ruff format --check .`:

```yaml
      - run: python scripts/check_dashboards.py dashboard/dashboards/*.json
```

- [ ] **Step 10: Tests**

Run: `pytest tests/analysis/test_dashboards.py tests/db/test_dashboard_queries.py -v && docker compose -f nas/docker-compose.yml --env-file nas/.env.example config -q`
Expected: PASS; Compose gültig. Schlägt eine Abfrage fehl, SQL im Generator korrigieren und Step 6 wiederholen.

- [ ] **Step 11: Lint und Commit**

```bash
ruff format . && ruff check .
git add dashboard/ scripts/check_dashboards.py tests/fixtures/dashboard_sql.py tests/analysis/test_dashboards.py tests/db/test_dashboard_queries.py nas/ .github/workflows/ci.yml
git commit -m "Grafana: Dashboards Überflüge, Datenqualität und Flugspur"
```

---

### Task 9: OSM-Grenzen in das Zonenformat umwandeln

**Files:**
- Create: `scripts/osm_to_geofences.py`
- Test: `tests/analysis/test_osm_to_geofences.py`

**Interfaces:**
- Consumes: Zonenformat aus Task 4 (`parse_zones` zur Prüfung im Test)
- Produces: `osm_to_geofences.convert(overpass: dict, *, source: str, circles: list[str], relevance_ft: int | None) -> dict` (FeatureCollection); `rings(ways: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]`; CLI `python scripts/osm_to_geofences.py overpass.json --source TEXT [--circle "Name,lat,lon,radius_m"]... [--relevance-ft N] > config/local/geofences.geojson`

- [ ] **Step 1: Tests schreiben** – `tests/analysis/test_osm_to_geofences.py`:

```python
import pytest
from analysis.zones import parse_zones
from osm_to_geofences import convert, rings


def way(*coords):
    return {"type": "way", "role": "outer", "geometry": [{"lat": la, "lon": lo} for la, lo in coords]}


def relation(name, members):
    return {"type": "relation", "id": 1, "tags": {"name": name, "boundary": "administrative"},
            "members": members}


SQUARE = [
    way((44.0, -31.0), (44.0, -30.9), (44.1, -30.9)),
    way((44.0, -31.0), (44.1, -31.0), (44.1, -30.9)),  # andersherum orientiert
]


def test_rings_joins_and_closes():
    (ring,) = rings([[(-31.0, 44.0), (-30.9, 44.0)], [(-30.9, 44.0), (-30.9, 44.1)],
                     [(-31.0, 44.0), (-30.9, 44.1)]])
    assert ring[0] == ring[-1] and len(ring) == 4


def test_rings_rejects_open_boundary():
    with pytest.raises(ValueError, match="geschlossen"):
        rings([[(-31.0, 44.0), (-30.9, 44.0)]])


def test_convert_relation_and_circle():
    data = {"elements": [relation("Beispielort", SQUARE)]}
    out = convert(data, source="OSM, ODbL, Abruf 2026-11-10",
                  circles=["Nahbereich,45.0,-30.0,1500"], relevance_ft=8000)
    zones = parse_zones(out, 10000)
    assert [(z.name, z.kind) for z in zones] == [("Beispielort", "polygon"), ("Nahbereich", "circle")]
    assert zones[0].source == "OSM, ODbL, Abruf 2026-11-10"
    assert all(z.relevance_max_alt_ft == 8000 for z in zones)
    assert zones[1].radius_m == 1500 and zones[1].ref_point == (-30.0, 45.0)


def test_inner_ring_becomes_hole():
    hole = {"type": "way", "role": "inner", "geometry": [
        {"lat": 44.04, "lon": -30.96}, {"lat": 44.04, "lon": -30.94},
        {"lat": 44.06, "lon": -30.94}, {"lat": 44.04, "lon": -30.96}]}
    out = convert({"elements": [relation("Mit Loch", [*SQUARE, hole])]}, source="t",
                  circles=[], relevance_ft=None)
    geometry = out["features"][0]["geometry"]
    assert geometry["type"] == "Polygon"
    assert len(geometry["coordinates"]) == 2  # Außenring + Loch
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `pytest tests/analysis/test_osm_to_geofences.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'osm_to_geofences'`.

- [ ] **Step 3: Implementierung** – `scripts/osm_to_geofences.py`:

```python
#!/usr/bin/env python3
"""Wandelt ein Overpass-Ergebnis (``out geom;``) in die Zonendatei für analysis um.

Beispiel (Ausgabe nur nach config/local/, nie committen):
  python scripts/osm_to_geofences.py config/local/overpass.json \
      --source "OSM, ODbL, Abruf JJJJ-MM-TT" --circle "Nahbereich,<lat>,<lon>,1500" \
      > config/local/geofences.geojson

OpenStreetMap-Daten stehen unter der ODbL; die Quelle steht je Zone in ``source``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

Coord = tuple[float, float]  # (lon, lat)


def rings(ways: list[list[Coord]]) -> list[list[Coord]]:
    """Fügt Wegstücke über gemeinsame Endpunkte zu geschlossenen Ringen zusammen."""
    pending = [list(w) for w in ways if len(w) >= 2]
    result: list[list[Coord]] = []
    while pending:
        ring = pending.pop(0)
        while ring[0] != ring[-1]:
            for i, w in enumerate(pending):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[-2::-1]
                else:
                    continue
                pending.pop(i)
                break
            else:
                raise ValueError("Grenze nicht geschlossen – Overpass-Ergebnis unvollständig?")
        result.append(ring)
    return result


def _inside(point: Coord, ring: list[Coord]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _polygon(relation: dict) -> dict:
    by_role: dict[str, list[list[Coord]]] = {"outer": [], "inner": []}
    for m in relation.get("members", []):
        if m.get("type") == "way" and m.get("role") in by_role and m.get("geometry"):
            by_role[m["role"]].append([(g["lon"], g["lat"]) for g in m["geometry"]])
    outers = rings(by_role["outer"])
    polygons = [[outer] for outer in outers]
    for inner in rings(by_role["inner"]):
        for poly in polygons:
            if _inside(inner[0], poly[0]):
                poly.append(inner)
                break
    coords = [[[list(c) for c in r] for r in poly] for poly in polygons]
    if len(coords) == 1:
        return {"type": "Polygon", "coordinates": coords[0]}
    return {"type": "MultiPolygon", "coordinates": coords}


def convert(
    overpass: dict, *, source: str, circles: list[str], relevance_ft: int | None
) -> dict:
    extra = {} if relevance_ft is None else {"relevance_max_alt_ft": relevance_ft}
    features = []
    for el in overpass.get("elements", []):
        if el.get("type") != "relation":
            continue
        name = (el.get("tags") or {}).get("name")
        if not name:
            continue
        features.append({"type": "Feature", "geometry": _polygon(el),
                         "properties": {"name": name, "source": source, **extra}})
    for spec in circles:
        name, lat, lon, radius = spec.rsplit(",", 3)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": {"name": name.strip(), "radius_m": float(radius),
                           "source": "eigener Kreis", **extra},
        })
    return {"type": "FeatureCollection", "features": features}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("overpass", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--circle", action="append", default=[],
                        help='"Name,lat,lon,radius_m" (mehrfach möglich)')
    parser.add_argument("--relevance-ft", type=int)
    args = parser.parse_args(argv)
    data = json.loads(args.overpass.read_text(encoding="utf-8"))
    out = convert(data, source=args.source, circles=args.circle, relevance_ft=args.relevance_ft)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Tests laufen lassen**

Run: `pytest tests/analysis/test_osm_to_geofences.py -v`
Expected: PASS.

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add scripts/osm_to_geofences.py tests/analysis/test_osm_to_geofences.py
git commit -m "Werkzeug: OSM-Grenzen in Zonendatei umwandeln"
```

---

### Task 10: End-to-End mit Analyse und Grafana

**Files:**
- Create: `tests/e2e/zones.example.geojson`
- Modify: `tests/e2e/compose.yml`, `tests/e2e/test_e2e.py`

**Interfaces:**
- Consumes: Container `analysis` (Task 7), Grafana-Provisioning und `build_dashboards` (Task 8), `dashboard_sql.substitute` (Task 8)

- [ ] **Step 1: E2E-Zone** – `tests/e2e/zones.example.geojson` (umschließt die Kreisbahnen der readsb-Attrappe um 50° N / 10° O vollständig):

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [10.0, 50.0] },
      "properties": { "name": "Testzone", "radius_m": 30000, "source": "synthetisch" }
    }
  ]
}
```

- [ ] **Step 2: Compose erweitern** – in `tests/e2e/compose.yml` vor `volumes:` (Top-Level) einfügen:

```yaml
  analysis:
    build:
      context: ../..
      dockerfile: analysis/Dockerfile
    depends_on:
      ingest:
        condition: service_started
    environment:
      ANALYSIS_DB_DSN: postgresql://flightdb_analysis:analysis@postgis:5432/flightdb
      ANALYSIS_INTERVAL_S: "5"
      ANALYSIS_SETTLE_S: "5"
      ANALYSIS_BER_LAT: "49.0"
      ANALYSIS_BER_LON: "8.0"
      ANALYSIS_ZONES_FILE: /zones/zones.example.geojson
    volumes:
      - ./zones.example.geojson:/zones/zones.example.geojson:ro

  grafana:
    image: grafana/grafana:13.2.6@sha256:b21409d7951ddcfd63a4b49083e4ef2cc35bc1437d071813bf82bfb238b00bca
    depends_on:
      postgis:
        condition: service_healthy
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
      POSTGRES_DB: flightdb
      DB_READONLY_PASSWORD: reader
    volumes:
      - ../../dashboard/provisioning:/etc/grafana/provisioning:ro
      - ../../dashboard/dashboards:/etc/grafana/dashboards:ro
    ports:
      - "3002:3000"
```

- [ ] **Step 3: Tests erweitern** – in `tests/e2e/test_e2e.py`:

Imports oben ergänzen:

```python
import base64
import json
import urllib.error
import urllib.request

import build_dashboards
from dashboard_sql import substitute
```

Konstante nach `DSN`: `GRAFANA = "http://localhost:3002"`.

In `stack()` die Log-Zeile ersetzen durch:

```python
        subprocess.run(
            [*COMPOSE, "logs", "--no-color", "recorder", "ingest", "analysis", "grafana"],
            check=False,
        )
```

In `wait_for` `except psycopg.Error:` ersetzen durch `except (psycopg.Error, OSError):`.

Am Dateiende anhängen:

```python
def grafana(path, payload=None):
    req = urllib.request.Request(
        GRAFANA + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Basic " + base64.b64encode(b"admin:admin").decode(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def test_analysis_builds_one_flight_and_event_per_aircraft(stack):
    wait_for(lambda: query("SELECT count(*) FROM overflight_events")[0] >= 3)
    assert query("SELECT count(*), count(DISTINCT icao24) FROM flights") == (3, 3)
    assert query("SELECT count(*) FROM overflight_events") == (3,)
    assert query("SELECT count(*) FROM analysis_runs WHERE status = 'failed'") == (0,)


def test_grafana_provisions_dashboards_and_runs_queries(stack):
    wait_for(lambda: grafana("/api/health").get("database") == "ok")
    uids = {d["uid"] for d in grafana("/api/search?type=dash-db")}
    assert {"flightdb-ueberfluege", "flightdb-datenqualitaet", "flightdb-flugspur"} <= uids
    for name, dashboard in build_dashboards.build().items():
        for sql in build_dashboards.queries(dashboard):
            res = grafana(
                "/api/ds/query",
                {
                    "from": "now-1h",
                    "to": "now",
                    "queries": [
                        {
                            "refId": "A",
                            "datasource": {"uid": "flightdb"},
                            "rawSql": substitute(sql, macros=False),
                            "format": "table",
                        }
                    ],
                },
            )
            assert "error" not in res["results"]["A"], (name, sql, res)
```

Hinweis: Die Analyse-Tests stehen hinter `test_connection_outage_loses_nothing`; sie prüfen damit auch, dass der Verbindungsabbruch keine doppelten Flüge erzeugt.

- [ ] **Step 4: E2E laufen lassen**

Run: `pytest -m e2e -v`
Expected: 4 PASS (Laufzeit mehrere Minuten). Bei Fehlschlag die am Ende ausgegebenen Container-Logs lesen.

- [ ] **Step 5: Lint und Commit**

```bash
ruff format . && ruff check .
git add tests/e2e/
git commit -m "End-to-End-Test um Analyse und Grafana erweitert"
```

---

### Task 11: Dokumentation

**Files:**
- Create: `docs/analysis.md`, `docs/dashboard.md`, `docs/decisions/0005-eigener-analyse-dienst.md`, `docs/decisions/0006-heuristische-einstufung.md`
- Modify: `docs/decisions/README.md`, `docs/data-model.md`, `docs/deployment-nas.md`, `docs/architecture.md`, `README.md`

- [ ] **Step 1: `docs/analysis.md`**

````markdown
# Auswertung: Flüge und Überflüge

Dienst `analysis` auf dem NAS (Rolle `flightdb_analysis`). Er liest `positions` und schreibt
`flights`, `overflight_events` und `analysis_runs`. Erfassung und Ingest laufen unabhängig davon.

## Ablauf eines Laufs

1. Zonendatei abgleichen (`ANALYSIS_ZONES_FILE`): geänderte Zonen erhalten eine neue Fassung.
2. Zeitfenster: bis zum Ende der eingelesenen Rohdateien abzüglich `ANALYSIS_SETTLE_S`; ab dem
   Ende des letzten erfolgreichen Laufs. Nachgelieferte ältere Dateien verschieben den Beginn nach
   vorn.
3. Flüge, die bis an das Fenster heranreichen, werden gelöscht und ab ihrem Beginn neu gebildet.
   Dadurch erscheinen Überflüge etwa eine Ingest-Periode nach dem Ereignis.
4. Flugbildung, Zonendurchquerungen, Kennwerte und Einstufung; alles in einer Transaktion.

## Flugbildung

Neuer Flug nach einer Pause von mehr als `ANALYSIS_FLIGHT_GAP_S` (600 s), bei Wechsel des
Rufzeichens oder nach einer Landung. Positionen am Boden gehören nicht zur Spur. Positionen, die
nur mit mehr als `ANALYSIS_MAX_SPEED_KT` (800 kt) erreichbar wären, gelten als Ausreißer.

## Überflugereignisse

Jedes Teilstück der Spur innerhalb einer Zone ist ein Ereignis. Ein- und Austritt werden auf der
Spur interpoliert. Der kleinste Abstand bezieht sich auf den Bezugspunkt der Zone (Kreismittelpunkt
bzw. `ref_point`). Die niedrigste Höhe ist die barometrische Höhe (Standardatmosphäre), **nicht**
die Höhe über Grund.

Datenqualität je Ereignis: Positionen in der Zone, größte Lücke zwischen Positionen, Überschneidung
mit einer Empfangslücke.

## Einstufung (heuristisch)

| Kategorie | Bedingung |
|---|---|
| `unknown` | weniger als 5 Positionen mit Höhe oder Höhenverlauf widerspricht Abstandsänderung |
| `arrival` | sinkt stärker als 300 ft/min, nähert sich BER, Abstand < 40 km |
| `departure` | steigt stärker als 300 ft/min, entfernt sich von BER, Abstand < 40 km |
| `overflight` | alle übrigen Fälle |

Grundlage sind die Positionen in der Zone plus je 120 s davor und danach. Die Begründung steht in
`category_basis`. Die Einstufung ist **keine** Zuordnung zu einem Flugverfahren; Flüge zu anderen
Plätzen oder Hubschrauber können als `overflight` oder `unknown` erscheinen.

## Parameter

| Variable | Standard | Bedeutung |
|---|---|---|
| `ANALYSIS_INTERVAL_S` | 300 | Abstand der Läufe |
| `ANALYSIS_SETTLE_S` | 120 | Sicherheitsabstand zum Ende der Rohdaten |
| `ANALYSIS_FLIGHT_GAP_S` | 600 | Pause, nach der ein neuer Flug beginnt |
| `ANALYSIS_MAX_SPEED_KT` | 800 | Grenze für Ausreißer |
| `ANALYSIS_CONTEXT_S` | 120 | Kontext für die Einstufung |
| `ANALYSIS_MIN_POSITIONS` | 5 | Mindestzahl für eine Einstufung |
| `ANALYSIS_VRATE_FPM` | 300 | Schwelle Steigen/Sinken |
| `ANALYSIS_BER_RADIUS_M` | 40000 | Umkreis um BER für Anflug/Abflug |
| `ANALYSIS_BER_LAT`, `ANALYSIS_BER_LON` | – | Flughafen-Referenzpunkt |
| `ANALYSIS_DEFAULT_RELEVANCE_FT` | 10000 | Relevanzgrenze, wenn die Zone keine angibt |

Alle Parameter eines Laufs stehen in `analysis_runs.params`.

## Zonendatei

`config/local/geofences.geojson` (gitignored), Vorlage: `config/geofences.example.geojson`.

- Kreis: `Point` + `radius_m`
- Polygon: `Polygon` oder `MultiPolygon`, optional `ref_point: [lon, lat]`
- immer: `name` (eindeutig); optional `relevance_max_alt_ft`, `source`

### Ortsteil- und Gemeindegrenzen aus OpenStreetMap

1. Abfrage lokal anlegen, z. B. `config/local/overpass.overpassql` (Namen einsetzen):

   ```text
   [out:json][timeout:90];
   area["name"="<Landkreis>"]["boundary"="administrative"]->.a;
   relation(area.a)["boundary"="administrative"]["name"~"^(<Gemeinde>|<Ortsteil 1>|<Ortsteil 2>)$"];
   out geom;
   ```

2. Abrufen: `curl -s --data-urlencode data@config/local/overpass.overpassql https://overpass-api.de/api/interpreter > config/local/overpass.json`
3. Umwandeln (Kreis um das Wohnumfeld ergänzen):

   ```bash
   python scripts/osm_to_geofences.py config/local/overpass.json \
     --source "OSM, ODbL, Abruf JJJJ-MM-TT" --circle "Nahbereich,<lat>,<lon>,<radius_m>" \
     > config/local/geofences.geojson
   ```

4. Ergebnis lokal prüfen (z. B. in QGIS als Vektorlayer; nicht auf Fremdseiten hochladen), dann `analysis zones`.

Ortsteile sind in OSM teils mit anderem `admin_level` oder als `boundary=place` erfasst; dann die
Abfrage anpassen. Die Overpass-Server sehen die abgefragten Namen.

## Befehle

```bash
sudo docker compose exec analysis python -m analysis zones            # Zonen laden
sudo docker compose exec analysis python -m analysis once             # ein Lauf
sudo docker compose exec analysis python -m analysis rebuild --from 2026-11-01 --to 2026-12-01
```

Zonenänderungen wirken nur auf neue Läufe; für zurückliegende Zeiträume `rebuild` ausführen.
````

- [ ] **Step 2: `docs/dashboard.md`**

```markdown
# Dashboards (Grafana)

Grafana läuft im NAS-Stack, nur im LAN (`http://<NAS>:${GRAFANA_LAN_PORT}`), Anmeldung mit
`admin` und `GRAFANA_ADMIN_PASSWORD`. Grafana liest ausschließlich über `flightdb_reader`.

| Dashboard | Inhalt |
|---|---|
| Überflüge | Kennzahlen, Zeitverlauf nach Kategorie, Tageszeit × Wochentag, Höhen, Richtungen, tiefste Überflüge, Karte mit Spuren und Zonen |
| Datenqualität | Empfangsabdeckung, Positionen und Dateien je Stunde, Uhrabweichung, Lücken, Ingest- und Analysestatus, Link zur Live-Karte |
| Flugspur | Spur, Höhe und Geschwindigkeit, Überflüge eines Flugs (Link aus der Tabelle „Tiefste Überflüge“) |

Filter „Überflüge: relevante“ zeigt nur Ereignisse unterhalb der Relevanzgrenze der Zone.
Kategorien sind heuristisch (siehe [analysis.md](analysis.md)).

## Änderungen

Dashboards werden aus `dashboard/build_dashboards.py` erzeugt:

```bash
python dashboard/build_dashboards.py
python scripts/check_dashboards.py dashboard/dashboards/*.json
```

In der Oberfläche gespeicherte Änderungen bleiben in der Grafana-Datenbank, bis sich die Datei im
Repo ändert. Dauerhafte Änderungen gehören in den Generator.

## Datenschutz

- Karten nutzen „Fit to data“; Kartenmittelpunkt und Zoom stehen nicht im Repo.
- Die tar1090-Adresse wird als Variable `tar1090` im Dashboard „Datenqualität“ eingetragen und
  in Grafana gespeichert, nicht im Repo.
- Die Hintergrundkarte lädt Kacheln von einem externen Anbieter; dieser sieht den betrachteten
  Kartenausschnitt.
- CSV-Export von Tabellen: Panel-Menü → *Inspect* → *Data*. Exporte nicht ins Repo legen.
```

- [ ] **Step 3: ADRs**

`docs/decisions/0005-eigener-analyse-dienst.md`:

```markdown
# 0005 – Eigener Analyse-Dienst

**Status:** angenommen

## Kontext

Aus den Positionen sollen Flüge und Überflugereignisse entstehen. Möglich wären eine Auswertung im
Ingest-Prozess, reines SQL in PostGIS oder ein eigener Dienst.

## Entscheidung

Ein eigener Dienst `analysis` (Python) bildet Flüge und steuert die Läufe; Schnittmengen, Abstände
und Interpolation rechnet PostGIS. Jeder Lauf wird mit Version und Parametern in `analysis_runs`
protokolliert. Migrationen spielt weiterhin nur `ingest` ein.

## Konsequenzen

- Fehler in der Auswertung beeinträchtigen Erfassung und Quittierung nicht.
- Auswertungen sind reproduzierbar und mit `rebuild` neu berechenbar.
- Ein zusätzlicher Container; geringe Last durch inkrementelle Läufe.
```

`docs/decisions/0006-heuristische-einstufung.md`:

```markdown
# 0006 – Heuristische Einstufung Anflug/Abflug

**Status:** angenommen

## Kontext

Die Unterscheidung von Anflügen und Abflügen ist für die Statistik wichtig. Eine belastbare
Zuordnung zu Bahn und Verfahren ist erst mit Referenzrouten (Meilenstein 4) möglich.

## Entscheidung

Bis dahin wird jedes Ereignis aus Höhenverlauf und Abstandsänderung zum Flughafen-Referenzpunkt
als `arrival`, `departure`, `overflight` oder `unknown` eingestuft. Die Begründung wird mit
gespeichert; unklare Fälle bleiben `unknown`. Dashboards kennzeichnen die Einstufung als
heuristisch.

## Konsequenzen

- Sofort nutzbare Aufteilung der Überflüge.
- Fehleinstufungen sind möglich und nachvollziehbar; sie sind kein Nachweis eines Verfahrens.
- Meilenstein 4 kann die Einstufung ersetzen, ohne das Schema umzubauen.
```

In `docs/decisions/README.md` die Tabelle ergänzen:

```markdown
| [0005](0005-eigener-analyse-dienst.md) | Eigener Analyse-Dienst | angenommen |
| [0006](0006-heuristische-einstufung.md) | Heuristische Einstufung Anflug/Abflug | angenommen |
```

- [ ] **Step 4: `docs/data-model.md`** – vor `## Herkunftskette` einfügen:

```markdown
## Auswertung (Meilenstein 3)

| Tabelle / View | Bedeutung |
|---|---|
| `geofences` | Zonen mit Gültigkeitszeitraum; Änderungen erzeugen eine neue Fassung |
| `flights` | zusammenhängende Spur eines Flugzeugs (`LineStringM`, M = Unix-Zeit) |
| `overflight_events` | eine Durchquerung einer Zonenfassung mit Kennwerten, Einstufung und Datenqualität |
| `analysis_runs` | jeder Lauf mit Art, Version, Parametern, Zeitfenster und Ergebnis |
| `overflights_daily` | Überflüge je Tag (Europe/Berlin), Zone, Kategorie, Relevanz |
| `data_coverage_daily` | aufgezeichnete Sekunden je Tag abzüglich Empfangslücken |

Herkunft eines Ereignisses: `overflight_events.analysis_run_id` → Parameter und Version;
`flight_id` → `flights` → Positionen des Flugzeugs im Zeitraum → `raw_file_id`.
```

und die Rollenzeile ersetzen durch:

```markdown
`flightdb_admin` (Eigentümer), `flightdb_ingest` (schreibt Erfassung), `flightdb_analysis`
(liest Erfassung, schreibt Auswertung), `flightdb_reader` (liest; n8n, Grafana).
```

- [ ] **Step 5: `docs/deployment-nas.md`** – Abschnitt 1 um `docker/flightdb/grafana` ergänzen (Befehl: `sudo mkdir -p <ssd>/docker/flightdb/grafana && sudo chown 472:472 <ssd>/docker/flightdb/grafana`, Hinweis „UID 472 = grafana“). Nach Abschnitt 3 einfügen:

````markdown
## 3a. Zonen

Zonendatei nach [analysis.md](analysis.md#zonendatei) erstellen und als
`config/local/geofences.geojson` im Repo-Ordner auf dem NAS ablegen (gitignored).
Ohne Zonendatei bricht jeder Analyse-Lauf mit einer Meldung ab; Erfassung und Ingest laufen weiter.
````

Abschnitt 5 ersetzen durch:

````markdown
## 5. Grafana und n8n

Grafana: `http://<NAS>:${GRAFANA_LAN_PORT}` (siehe [dashboard.md](dashboard.md)).
n8n: Verbindung zu `NAS-IP:${DB_LAN_PORT}`, Datenbank `flightdb`, Benutzer `flightdb_reader`.
Beide Ports nur im LAN freigeben (DSM-Firewall), nicht ins Internet weiterleiten.

**Bestehende Datenbank** (vor Meilenstein 3 angelegt): Die Rolle `flightdb_analysis` legt die
Migration ohne Passwort an. Einmalig:

```bash
sudo docker compose exec postgis psql -U flightdb_admin -d flightdb \
  -c "ALTER ROLE flightdb_analysis LOGIN PASSWORD '<DB_ANALYSIS_PASSWORD>'"
```
````

Abschnitt 6 um `sudo docker compose logs analysis` und
`... -c "SELECT id, kind, status, n_events, error FROM analysis_runs ORDER BY id DESC LIMIT 5"` ergänzen.

- [ ] **Step 6: `docs/architecture.md`** – Zeile `├─ api ...` bleibt; Datenfluss-Punkt 5 ersetzen durch: „`analysis` läuft alle 5 Minuten inkrementell und erzeugt Flüge und Überflugereignisse (Details: [analysis.md](analysis.md)).“

- [ ] **Step 7: `README.md`** – Status-Abschnitt um „M3: Software fertig und getestet, Abnahme mit Hardware ausstehend“ ergänzen; Doku-Tabelle um `docs/analysis.md` (Auswertung: Flüge, Überflüge, Zonen) und `docs/dashboard.md` (Grafana-Dashboards) ergänzen.

- [ ] **Step 8: Prüfen und Commit**

Run: `pytest && ruff format . && ruff check . && git diff --cached --stat`
Expected: alle PASS.

```bash
git add docs/ README.md
git commit -m "Dokumentation: Auswertung, Dashboards, ADR 0005/0006, Status Meilenstein 3"
```

---

## Abschluss

- [ ] `pytest` und `pytest -m e2e` grün, `ruff check .` und `ruff format --check .` sauber.
- [ ] `git log --format='%an <%ae> | %cn <%ce>' main..m3-analyse | sort -u` zeigt nur die noreply-Adresse; keine Attribution in Nachrichten (`git log main..m3-analyse --format=%B | grep -i claude` ohne Treffer).
- [ ] Manuelle Sichtprüfung: E2E-Stack mit `docker compose -f tests/e2e/compose.yml up -d --build` starten, nach einigen Minuten `http://localhost:3002` (admin/admin) öffnen, alle Panels der drei Dashboards ansehen, danach `docker compose -f tests/e2e/compose.yml down -v`.
- [ ] Danach superpowers:finishing-a-development-branch.
