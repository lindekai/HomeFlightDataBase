#!/bin/bash
# Läuft einmalig beim ersten Start des PostGIS-Containers (leeres Datenverzeichnis).
# Legt die Anwendungsrollen mit Passwörtern aus der .env an; Rechte vergibt die Migration.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v ingest_pw="$DB_INGEST_PASSWORD" -v reader_pw="$DB_READONLY_PASSWORD" <<'SQL'
CREATE ROLE flightdb_ingest LOGIN PASSWORD :'ingest_pw';
CREATE ROLE flightdb_reader LOGIN PASSWORD :'reader_pw';
SQL
