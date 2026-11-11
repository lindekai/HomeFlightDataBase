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
