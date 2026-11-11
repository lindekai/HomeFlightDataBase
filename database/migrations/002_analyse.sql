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

-- Aufgezeichnete Sekunden je Tag (eingelesene Dateizeiträume) und Lücken darin.
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
  -- Nur der Teil der Lücken innerhalb der Dateizeiträume zählt (Neustart-Lücken liegen
  -- zwischen Dateien und fehlen schon in recorded_s); überlappende Lücken zählen einmal.
  coalesce((SELECT sum(extract(epoch FROM upper(r) - lower(r)))
    FROM unnest(
      (SELECT range_agg(tstzrange(g.gap_start, g.gap_end))
         FROM reception_gaps g
         WHERE g.receiver_id = days.receiver_id
           AND g.gap_start < days.day_end AND g.gap_end > days.day_start)
      * (SELECT range_agg(tstzrange(f.period_start, f.period_end))
           FROM raw_files f
           WHERE f.receiver_id = days.receiver_id AND f.status = 'ingested'
             AND f.period_start < days.day_end AND f.period_end > days.day_start)
      * tstzmultirange(tstzrange(days.day_start, days.day_end))) AS r), 0) AS gap_s,
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
