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
