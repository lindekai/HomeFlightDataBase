# Meilenstein 2 – Empfang und Speicherung: Design

**Stand:** 2026-11-09 · **Status:** abgestimmt, zur Durchsicht

Grundlage: [architecture.md](../../architecture.md), ADR [0001](../../decisions/0001-getrennte-empfangsstation.md)–[0004](../../decisions/0004-eigene-postgis-instanz.md).

## 1. Ziel und Umfang

Kontinuierliche, verlustarme und nachvollziehbare Erfassung aller empfangenen Flugzeugpositionen: Empfang auf dem Raspberry Pi, unveränderte Archivierung der Rohdaten mit Prüfsumme, normalisierte Speicherung in PostGIS auf dem NAS.

**Im Umfang:**

- Docker-Setup der Empfangsstation inkl. Einspeisung an vier Netzwerke
- `recorder` (Pi), `ingest` (NAS), PostGIS-Schema für die Erfassung
- Healthchecks, Logging, Statusview, nächtliches DB-Backup
- Tests mit synthetischen Daten, GitHub Actions

**Nicht im Umfang (spätere Meilensteine):** Flugsegmentierung, Geofences, Überflüge (M3); Referenzrouten (M4); Benachrichtigungen, Berichte, n8n-Workflows (M5); externe Backups (M6).

## 2. Getroffene Entscheidungen

| Thema | Entscheidung |
|---|---|
| Rohdatenformat | Dekodierte Momentaufnahmen von readsb (`aircraft.json`), 1× pro Sekunde, unverändert |
| Beast-Rohnachrichten | nicht erfasst; später ohne Architekturänderung ergänzbar |
| Aufbewahrung | Rohdaten-Archiv und Datenbank unbegrenzt; DB monatlich partitioniert |
| Räumliche Eingrenzung | keine; Neubewertung nach Messbetrieb |
| Einspeisung | adsb.lol, OpenSky Network, Flightradar24, FlightAware |
| Pi-Setup | Raspberry Pi OS Lite + Docker Compose aus dem Repo (`receiver/`) |

## 3. Empfangsstation (Pi)

### 3.1 Container (`receiver/docker-compose.yml`)

| Container | Image (Basis) | Aufgabe |
|---|---|---|
| `ultrafeeder` | sdr-enthusiasts `docker-adsb-ultrafeeder` | readsb, tar1090 (LAN), Einspeisung adsb.lol, MLAT-Client |
| `fr24feed` | sdr-enthusiasts `docker-flightradar24` | Einspeisung Flightradar24 |
| `piaware` | sdr-enthusiasts `docker-piaware` | Einspeisung FlightAware |
| `opensky` | sdr-enthusiasts `docker-opensky-network` | Einspeisung OpenSky Network |
| `recorder` | eigenes Image, Python-Standardbibliothek | Rohdatenaufzeichnung |

Image-Versionen werden fest angegeben (kein `latest`). Standort, Feeder-Schlüssel und Zugangsdaten stehen ausschließlich in `receiver/.env` (gitignored); im Repo liegt `receiver/.env.example`. Wo Netzwerke es anbieten, wird die öffentliche Standortanzeige ungenau gestellt.

### 3.2 recorder

Ablauf je Sekunde:

1. `aircraft.json` von readsb lesen (HTTP im Docker-Netz).
2. Eine Zeile an die aktuelle Stundendatei anhängen:
   `{"recorder_ts": <UTC ISO-8601>, "receiver_id": "<id>", "recorder_version": "<x.y.z>", "data": <aircraft.json unverändert>}`
3. Dateiname: `<receiver_id>/JJJJ/MM/TT/HH.ndjson.gz` (UTC), im Verzeichnis `current/`.

Stundenwechsel:

1. Datei schließen, SHA-256 berechnen, `<datei>.sha256` schreiben.
2. Beide Dateien atomar nach `complete/` verschieben.

Lücken: Liefert readsb keine Daten oder ist der readsb-Zeitstempel `now` älter als 5 s, wird eine Zeile `{"type": "gap", "from": …, "to": …, "reason": …}` geschrieben, sobald Daten wieder fließen.

Unsauberes Ende (Absturz, Stromausfall): Beim Start wird eine vorhandene Datei in `current/` bis zur letzten vollständigen Zeile übernommen, abgeschlossen und im Dateinamen als `.partial` gekennzeichnet; die Unterbrechung wird als Lücke protokolliert.

Aufräumen: Dateien in `complete/` werden gelöscht, wenn eine Quittung in `acked/` existiert **und** die Datei älter als `RECEIVER_RETENTION_DAYS` (Standard 7) ist. Ohne Quittung wird nie gelöscht. Unter 10 % freiem Speicher: Warnung im Log und im Status, kein Löschen.

### 3.3 Betriebssystem

- chrony als NTP-Client; der recorder liest den Offset aus und vermerkt ihn stündlich als Zeile `{"type": "clock", "offset_s": …}`. Offset > 1 s: Warnung.
- Datenverzeichnis bevorzugt auf USB-SSD statt SD-Karte.
- Docker-Logrotation (`max-size`, `max-file`) für alle Container.

## 4. Übertragung und Ingest (NAS)

### 4.1 Abholung

- Container `ingest` läuft dauerhaft und startet alle 5 Minuten einen Durchlauf.
- `rsync` über SSH zum Pi. Eigener Benutzer auf dem Pi, eigener Schlüssel, `rrsync` als erzwungenes Kommando: lesend nur `complete/`, schreibend nur `acked/`.
- Es werden nur Dateien mit zugehöriger `.sha256` übertragen.

### 4.2 Verarbeitung je Datei

1. Prüfsumme verifizieren. Fehler → Quarantäne-Verzeichnis, Log-Warnung, keine Quittung.
2. Unverändert ins Archiv kopieren: `RAW_ARCHIVE_DIR/<receiver_id>/JJJJ/MM/TT/` inkl. `.sha256`.
3. In `raw_files` registrieren. Bereits bekannte Prüfsumme → überspringen (idempotent).
4. Normalisieren (siehe 4.3) und per `COPY` laden – eine Transaktion pro Datei.
5. Status in `raw_files` auf `ingested` setzen, dann Quittung `acked/<datei>.ack` auf dem Pi ablegen.

### 4.3 Normalisierung

- Je Flugzeug einer Momentaufnahme mit gültiger Position: Positionszeitpunkt = `data.now − seen_pos`.
- Duplikate (gleicher Empfänger, ICAO24, Positionszeitpunkt) werden verworfen.
- Quelle (`type`: adsb_icao, mlat, tisb_* …), NIC, NACp, SIL und RSSI werden übernommen.
- Lückenzeilen → `reception_gaps`; Clock-Zeilen → Spalte in `raw_files`.
- Einheiten unverändert wie readsb (ft, kt, ft/min), dokumentiert im Schema.

### 4.4 Neuaufbau

`ingest rebuild [--from DATUM] [--to DATUM]` liest Archivdateien neu ein. Bestehende Positionen des Zeitraums werden ersetzt; das Archiv wird nie verändert.

## 5. Datenbank

### 5.1 Tabellen

| Tabelle | Wesentliche Spalten |
|---|---|
| `receivers` | `id`, `label`, `location` (Point, nur lokal befüllt), `antenna`, `sdr`, `valid_from`, `valid_to` |
| `raw_files` | `id`, `receiver_id`, `path`, `sha256`, `size_bytes`, `period_start`, `period_end`, `partial`, `clock_offset_max_s`, `fetched_at`, `status`, `ingest_version` |
| `reception_gaps` | `id`, `receiver_id`, `gap_start`, `gap_end`, `reason`, `raw_file_id` |
| `aircraft` | `icao24` (PK), `registration`, `type_code`, `first_seen`, `last_seen` |
| `positions` | `ts`, `receiver_id`, `icao24`, `callsign`, `geom` (Point, SRID 4326), `alt_baro_ft`, `alt_geom_ft`, `gs_kt`, `track_deg`, `baro_rate_fpm`, `squawk`, `source_type`, `nic`, `nac_p`, `sil`, `rssi_dbfs`, `raw_file_id` |

`positions`: Eindeutigkeit über (`receiver_id`, `icao24`, `ts`); monatliche Partitionierung über `ts`; `ingest` legt die Partitionen für den laufenden und den nächsten Monat an.

### 5.2 Indizes

- BRIN auf `positions.ts`
- GiST auf `positions.geom`
- B-Tree auf `positions (icao24, ts)`

### 5.3 Rollen

| Rolle | Rechte |
|---|---|
| `flightdb_admin` | Eigentümer, Migrationen |
| `flightdb_ingest` | INSERT/UPDATE auf Erfassungstabellen, Partitionen anlegen |
| `flightdb_reader` | nur SELECT (n8n, Grafana) |

### 5.4 Migrationen

Nummerierte SQL-Dateien in `database/migrations/`; `ingest` spielt sie beim Start ein und protokolliert sie in `schema_migrations`.

### 5.5 Statusview `ingest_status`

Letzte ingestierte Datei, Rückstand (nicht ingestierte Stunden), Anzahl und Dauer der Lücken der letzten 24 h, letzter gemeldeter freier Pufferspeicher des Pi.

## 6. Fehlerbehandlung und Überwachung

### 6.1 Healthchecks

| Dienst | gesund, wenn |
|---|---|
| `recorder` | letzte Schreiboperation < 10 s und readsb-Daten frisch |
| `ultrafeeder` | eingebauter Healthcheck |
| `ingest` | letzter Durchlauf erfolgreich und < 15 min alt |
| `postgis` | `pg_isready` |

Alle Container: `restart: unless-stopped`.

### 6.2 Störungen

| Störung | Verhalten |
|---|---|
| WLAN-Ausfall | Pufferung auf dem Pi, spätere Abholung |
| NAS-Ausfall | wie WLAN-Ausfall |
| SDR hängt | Healthcheck → Neustart; Lücke protokolliert |
| Stromausfall Pi | Datei als `.partial` abgeschlossen; Lücke protokolliert |
| Uhrabweichung > 1 s | Warnung; Wert in `raw_files` |
| Prüfsummenfehler | Quarantäne, keine Quittung |
| DB-Fehler beim Laden | Rollback der Datei, Wiederholung im nächsten Durchlauf |

### 6.3 Logging und Backup

- Strukturierte JSON-Logs nach stdout, Docker-Logrotation.
- Nächtlicher `pg_dump` (komprimiert) auf das HDD-Volume, Aufbewahrung der letzten 14 Dumps. Primäre Sicherung ist das Rohdaten-Archiv.

## 7. Tests

### 7.1 Synthetische Testdaten

- Empfänger-ID `TEST`, ICAO24-Kennungen mit Präfix `ff`, Dateinamen mit `synthetic`, Feld `"synthetic": true` in jeder Zeile.
- `ingest` verweigert Daten mit Empfänger-ID `TEST` oder `"synthetic": true`, wenn `FLIGHTDB_ENV=production`.

### 7.2 Testebenen

| Ebene | Inhalt |
|---|---|
| Unit `recorder` | Stundenwechsel, Prüfsumme, Lücken, `.partial`, Aufräumregeln |
| Unit `ingest` | Positionszeitpunkt, Duplikate, Prüfsummenfehler, TEST-Sperre |
| Integration DB | Migrationen, Partitionen, `COPY`, Rollenrechte, Idempotenz, `rebuild` |
| End-to-End | readsb-Attrappe → recorder → rsync/SSH → ingest → PostGIS; Zeilenzahlen und Prüfsummen |

Werkzeuge: pytest, ruff; Integration und End-to-End mit Docker Compose. GitHub Actions führt Lint und Tests bei jedem Push aus, ohne Secrets.

### 7.3 Abnahme mit echter Hardware

- 7 Tage Dauerbetrieb ohne manuellen Eingriff
- alle Stundendateien archiviert, quittiert, Prüfsummen bestätigt
- WLAN-Unterbrechung ohne Datenverlust überbrückt
- gezogener SDR als Lücke in `reception_gaps`
- gemessener Speicherbedarf pro Tag (Archiv und DB) in `docs/` dokumentiert

## 8. Verzeichnisstruktur (neu in M2)

```text
receiver/
  docker-compose.yml
  .env.example
  recorder/            Python-Paket + Dockerfile
nas/
  docker-compose.yml   postgis, ingest, backup
  .env.example
ingest/                Python-Paket + Dockerfile
database/
  migrations/
tests/
  fixtures/synthetic/
  e2e/
.github/workflows/ci.yml
```

## 9. Abschätzung Speicherbedarf

Vor Messung: Archiv ca. 100–300 GB/Jahr, Datenbank ca. 100–200 GB/Jahr. Wird in der Abnahme durch Messwerte ersetzt.

## 10. Offene Punkte (blockieren die Entwicklung nicht)

- Modell des Raspberry Pi und Eignung der vorhandenen DVB-T-Sticks
- Hardwarebeschaffung nach Prüfung
- Feeder-Registrierungen (Schlüssel) bei den vier Netzwerken
