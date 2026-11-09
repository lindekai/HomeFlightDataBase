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
