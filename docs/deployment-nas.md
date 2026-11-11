# Deployment auf dem NAS

Voraussetzung: Container Manager (DSM 7.2+), SSH-Zugang zum NAS für die Ersteinrichtung.
Bestehende Container (z. B. n8n) werden nicht verändert.

## 1. Verzeichnisse

Auf dem SSD-Volume: `docker/flightdb/postgres`, `docker/flightdb/ingest-work`, `docker/flightdb/ssh`, `docker/flightdb/grafana`.
Auf dem HDD-Volume: `flightdb/raw`, `flightdb/backups`.

```bash
sudo mkdir -p <ssd>/docker/flightdb/{postgres,ingest-work,ssh} <hdd>/flightdb/{raw,backups}
sudo chown 1000:1000 <ssd>/docker/flightdb/{ingest-work,ssh} <hdd>/flightdb/raw
sudo chown 999:999 <hdd>/flightdb/backups
```

```bash
sudo mkdir -p <ssd>/docker/flightdb/grafana && sudo chown 472:472 <ssd>/docker/flightdb/grafana
```

(UID 999 = postgres im PostGIS-Image, UID 1000 = ingest, UID 472 = grafana.)

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

Die beiden `.pub`-Dateien werden auf dem Pi eingetragen (siehe [deployment-receiver.md](deployment-receiver.md)).

## 3a. Zonen

Zonendatei nach [analysis.md](analysis.md#zonendatei) erstellen und als
`config/local/geofences.geojson` im Repo-Ordner auf dem NAS ablegen (gitignored).
Ohne Zonendatei bricht jeder Analyse-Lauf mit einer Meldung ab; Erfassung und Ingest laufen weiter.

## 4. Start

```bash
cd <ssd>/docker/flightdb/repo/nas
sudo docker compose --env-file .env up -d --build
sudo docker compose ps
sudo docker compose logs -f ingest
```

Alternativ im Container Manager unter *Projekt → Erstellen* mit diesem Ordner.

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

## 6. Prüfen

```bash
sudo docker compose exec postgis psql -U flightdb_admin -d flightdb -c "SELECT * FROM ingest_status"
sudo docker compose logs analysis
sudo docker compose exec postgis psql -U flightdb_admin -d flightdb \
  -c "SELECT id, kind, status, n_events, error FROM analysis_runs ORDER BY id DESC LIMIT 5"
```

## 7. Wiederherstellung

```bash
# Datenbank aus Dump:
sudo docker compose exec -T postgis pg_restore -U flightdb_admin -d flightdb --clean --if-exists \
  < <hdd>/flightdb/backups/flightdb_<zeit>.dump
# Oder komplett aus dem Rohdaten-Archiv neu aufbauen:
sudo docker compose run --rm ingest python -m ingest rebuild --from 2026-01-01 --to 2100-01-01
```
