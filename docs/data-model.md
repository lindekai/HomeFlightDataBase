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

## Auswertung (Meilenstein 3)

| Tabelle / View | Bedeutung |
|---|---|
| `geofences` | Zonen mit Gültigkeitszeitraum; Änderungen erzeugen eine neue Fassung |
| `flights` | zusammenhängende Spur eines Flugzeugs (`LineStringM`, M = Unix-Zeit) |
| `overflight_events` | eine Durchquerung einer Zonenfassung mit Kennwerten, Einstufung und Datenqualität |
| `analysis_runs` | jeder Lauf mit Art, Version, Parametern, Zeitfenster und Ergebnis |
| `overflights_daily` | Überflüge je Tag (Europe/Berlin), Zone, Kategorie, Relevanz |
| `data_coverage_daily` | aufgezeichnete Sekunden je Tag (`recorded_s`) und Empfangslücken innerhalb der Dateizeiträume (`gap_s`, Überlappungen einmal) |

`overflight_events.min_alt_ft` ist die niedrigste barometrische Höhe des Ereignisses. Sie
berücksichtigt die Positionen innerhalb der Zone und die an Ein- und Austritt interpolierten
Höhen (Details: [analysis.md](analysis.md#überflugereignisse)).

Herkunft eines Ereignisses: `overflight_events.analysis_run_id` → Parameter und Version;
`flight_id` → `flights` → Positionen des Flugzeugs im Zeitraum → `raw_file_id`.

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

## Herkunftskette

`positions.raw_file_id` → `raw_files.path` + `sha256` → Datei im Archiv → `.sha256`.
Jede Position ist damit auf eine unveränderte, prüfsummengesicherte Rohdatei zurückführbar.

## Rollen

`flightdb_admin` (Eigentümer), `flightdb_ingest` (schreibt Erfassung), `flightdb_analysis`
(liest Erfassung, schreibt Auswertung), `flightdb_reader` (liest; n8n, Grafana).
