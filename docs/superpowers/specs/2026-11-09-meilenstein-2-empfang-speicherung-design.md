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
2. Hat sich der readsb-Zeitstempel `now` geändert, eine Zeile an die aktuelle Datei anhängen:
   `{"type": "snapshot", "recorder_ts": <UTC ISO-8601>, "receiver_id": "<id>", "recorder_version": "<x.y.z>", "data": <aircraft.json unverändert>}`
   Alle Zeilentypen (`snapshot`, `gap`, `clock`, `status`) tragen `type`, `recorder_ts`, `receiver_id` und `recorder_version`; bei Testbetrieb zusätzlich `"synthetic": true`.
3. Die aktuelle Datei liegt **unkomprimiert** in `current/<receiver_id>/JJJJ/MM/TT/<JJJJMMTT>T<HHMMSS>Z.ndjson`; der Zeitstempel im Namen ist der Beginn der Datei (UTC). Jede Zeile wird sofort an das Betriebssystem übergeben (`flush`).

Periodenwechsel (Standard: volle Stunde, konfigurierbar über `RECORDER_ROTATE_SECONDS`):

1. Datei schließen, gzip-komprimieren, SHA-256 berechnen.
2. Atomar nach `complete/…/<name>.ndjson.gz` verschieben, danach `<name>.ndjson.gz.sha256` (Format wie `sha256sum`) anlegen. Erst mit der `.sha256` gilt eine Datei als abholbereit.

Lücken: Liefert readsb keine Daten oder ist der readsb-Zeitstempel `now` älter als 5 s, wird eine Zeile `{"type": "gap", "from": …, "to": …, "reason": "no_data" | "stale_data"}` geschrieben, sobald Daten wieder fließen bzw. beim Beenden. Beim Start wird die Zeit seit der letzten Dateiänderung als Lücke `recorder_restart` protokolliert.

Unsauberes Ende (Absturz, Stromausfall): Beim Start wird eine vorhandene Datei in `current/` bis zur letzten vollständigen Zeile übernommen und als `<name>.partial.ndjson.gz` abgeschlossen. Beim regulären Beenden wird die laufende Datei ebenfalls als `.partial` abgeschlossen.

Stündlich: Zeile `{"type": "clock", "offset_s": …}` (siehe 3.3) und `{"type": "status", "free_bytes": …, "free_ratio": …}` zum freien Pufferspeicher.

Aufräumen (stündlich): Dateien in `complete/` werden gelöscht, wenn eine Quittung in `acked/` existiert **und** die Datei älter als `RECEIVER_RETENTION_DAYS` (Standard 7) ist. Ohne Quittung wird nie gelöscht. Verwaiste Quittungen (Datei fehlt) werden nach derselben Frist entfernt. Unter 10 % freiem Speicher: Warnung im Log und im Status, unquittierte Dateien bleiben erhalten.

### 3.3 Betriebssystem

- chrony als NTP-Client des Pi. Der recorder misst die Abweichung der Systemuhr stündlich selbst per SNTP-Abfrage (`RECORDER_NTP_SERVER`) und vermerkt sie als Zeile `{"type": "clock", "offset_s": …}` (`null`, wenn nicht messbar). Abweichung > 1 s: Warnung.
- Container `autoheal` startet Container mit Label `autoheal=true` neu, sobald ihr Healthcheck fehlschlägt (Docker selbst startet nur beendete, nicht „unhealthy“ Container neu).
- Datenverzeichnis bevorzugt auf USB-SSD statt SD-Karte.
- Docker-Logrotation (`max-size`, `max-file`) für alle Container.

## 4. Übertragung und Ingest (NAS)

### 4.1 Abholung

- Container `ingest` läuft dauerhaft und startet alle 5 Minuten einen Durchlauf.
- `rsync` über SSH zum Pi. Eigener Benutzer `flightdb-sync` auf dem Pi mit **zwei Schlüsseln** und `rrsync` als erzwungenem Kommando: Schlüssel „read“ nur lesend auf `complete/` (`rrsync -ro`), Schlüssel „ack“ nur schreibend auf `acked/` (`rrsync -wo`).
- Übertragen werden `*.ndjson.gz` und `*.sha256`. Bereits archivierte Dateien werden über `--compare-dest=<Archiv>` übersprungen.
- Der Host-Schlüssel des Pi wird beim ersten Kontakt gespeichert und danach geprüft (`StrictHostKeyChecking=accept-new`).
- Schlägt die Abholung fehl (Pi nicht erreichbar), wird nur gewarnt; der Durchlauf verarbeitet trotzdem alles bereits Vorhandene.

### 4.2 Verarbeitung je Datei

1. Ohne `.sha256` wird die Datei übersprungen. Prüfsumme verifizieren; Fehler → Quarantäne-Verzeichnis, Log-Warnung, keine Quittung.
2. Einlesen und Normalisieren (siehe 4.3). Nicht lesbar, `receiver_id` passt nicht zum Pfad oder Schutzsperre für Testdaten (7.1) → Quarantäne.
3. In `raw_files` registrieren. Bereits als `ingested` bekannte Prüfsumme → überspringen und erneut quittieren (idempotent). Gleicher Pfad mit anderer Prüfsumme → Quarantäne.
4. Unverändert ins Archiv kopieren: `RAW_ARCHIVE_DIR/<receiver_id>/JJJJ/MM/TT/` inkl. `.sha256`; Kopie per Prüfsumme verifizieren.
5. Per `COPY` laden – eine Transaktion pro Datei – und Status `ingested` setzen.
6. Quittung `acked/<datei>.ack` (Inhalt: Prüfsumme) auf dem Pi ablegen.

Dateien mit Status `registered` oder `failed` werden zu Beginn jedes Durchlaufs aus dem Archiv erneut geladen, sofern ihre Archiv-Prüfsumme stimmt. Ist die Datenbank nicht erreichbar, bricht der Durchlauf ab; die abgeholten Dateien bleiben im Staging.

### 4.3 Normalisierung

- Je Flugzeug einer Momentaufnahme mit gültiger Position: Positionszeitpunkt = `data.now − seen_pos`, gerundet auf 0,1 s (Auflösung von readsb).
- `alt_baro = "ground"` → `on_ground = true`, barometrische Höhe leer.
- Duplikate (gleicher Empfänger, ICAO24, Positionszeitpunkt) werden verworfen – innerhalb einer Datei und dateiübergreifend (`ON CONFLICT DO NOTHING`).
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
| `positions` | `ts`, `receiver_id`, `icao24`, `callsign`, `geom` (Point, SRID 4326), `on_ground`, `alt_baro_ft`, `alt_geom_ft`, `gs_kt`, `track_deg`, `baro_rate_fpm`, `squawk`, `source_type`, `nic`, `nac_p`, `sil`, `rssi_dbfs`, `raw_file_id` |

`positions`: Primärschlüssel (`receiver_id`, `icao24`, `ts`); monatliche Partitionierung über `ts`; `ingest` legt die Partitionen für den laufenden und den nächsten Monat sowie bei Bedarf für ältere Daten an. `raw_file_id` ist bewusst ohne Fremdschlüssel (kein Zusatzindex auf der größten Tabelle); gelöscht wird bei `rebuild` über `raw_file_id` und den Zeitraum der Datei.

### 5.2 Indizes

- BRIN auf `positions.ts`
- GiST auf `positions.geom`
- Flugspuren je Flugzeug über den Primärschlüssel (`receiver_id`, `icao24`, `ts`) – kein zusätzlicher B-Tree

### 5.3 Rollen

| Rolle | Rechte |
|---|---|
| `flightdb_admin` | Eigentümer, Migrationen, Partitionen anlegen (`ingest` nutzt dafür eine eigene Admin-Verbindung) |
| `flightdb_ingest` | SELECT/INSERT/UPDATE/DELETE auf Erfassungstabellen |
| `flightdb_reader` | nur SELECT (n8n, Grafana) |

Passwörter der Rollen setzt ein Init-Skript des PostGIS-Containers beim ersten Start aus der `.env`.

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

Alle Container: `restart: unless-stopped`. Auf dem Pi startet `autoheal` „unhealthy“ Container neu. Auf dem NAS wird bewusst kein `autoheal` eingesetzt (Zugriff auf den Docker-Socket neben produktiven Containern); der Status ist im Container Manager sichtbar.

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
  init/                Rollen-Passwörter beim ersten Start
  backup/              Backup-Skript
scripts/               Git-Hooks gegen sensible Inhalte
tests/
  fixtures/synthetic/
  recorder/ ingest/ db/
  e2e/
.github/workflows/ci.yml
```

## 9. Abschätzung Speicherbedarf

Vor Messung: Archiv ca. 100–300 GB/Jahr, Datenbank ca. 100–200 GB/Jahr. Wird in der Abnahme durch Messwerte ersetzt.

## 10. Offene Punkte (blockieren die Entwicklung nicht)

- Modell des Raspberry Pi und Eignung der vorhandenen DVB-T-Sticks
- Hardwarebeschaffung nach Prüfung
- Feeder-Registrierungen (Schlüssel) bei den vier Netzwerken
