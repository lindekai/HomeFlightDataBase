# Meilenstein 3 – Geofences und Dashboard: Design

**Stand:** 2026-11-10 · **Status:** abgestimmt, zur Durchsicht

Grundlage: [architecture.md](../../architecture.md), [data-model.md](../../data-model.md), Design [Meilenstein 2](2026-11-09-meilenstein-2-empfang-speicherung-design.md).

## 1. Ziel und Umfang

Überwachungszonen festlegen, Überflüge aus den erfassten Positionen erkennen und in Grafana darstellen. Ergebnis: eine überprüfbare Überflugstatistik.

**Im Umfang:**

- Zonen (Kreise und Polygone) aus einer lokalen GeoJSON-Datei, versioniert in der Datenbank
- Flugbildung aus `positions`, Überflugereignisse je Zone, heuristische Einstufung Anflug/Abflug
- Dienst `analysis` auf dem NAS mit inkrementellen Läufen und Neuberechnung
- Grafana mit den Dashboards „Überflüge“ und „Datenqualität“
- Tests mit synthetischen Spuren, Erweiterung des E2E-Tests und der CI

**Nicht im Umfang:** Referenzrouten, Verfahrenszuordnung, Auffälligkeiten der Kategorien B–E, Zeitraumvergleiche und Korridorveränderungen (M4); Exporte CSV/GeoJSON/GPX, Berichte, n8n-Workflows, Benachrichtigungen (M5).

## 2. Getroffene Entscheidungen

| Thema | Entscheidung |
|---|---|
| Zonenquelle | Ortsteile und Gemeinde aus OpenStreetMap (ODbL) plus ein Kreis um das Wohnumfeld; eigene Polygone ergänzbar |
| Höhengrenze | Alle Durchquerungen werden gespeichert; je Zone eine Relevanzgrenze (Standard 10.000 ft ≈ 3.000 m), Dashboard filtert standardmäßig auf relevante |
| Anflug/Abflug | Heuristische Einstufung mit Begründung, als heuristisch gekennzeichnet; M4 ersetzt sie durch Verfahrenszuordnung |
| Ort der Auswertung | Eigener Dienst `analysis` (Python), Geometrie in PostGIS |
| Darstellung | Eigener Grafana-Container im NAS-Stack, nur lesender DB-Zugriff |
| Live-Karte | tar1090 auf dem Pi; das Dashboard verlinkt nur darauf |
| Kartenkacheln | Externer Standardanbieter von Grafana; der Anbieter sieht den betrachteten Ausschnitt (bewusst akzeptiert) |

## 3. Datenmodell (Migration `002_analyse.sql`)

Einheiten wie in M2: Höhen in ft, Geschwindigkeit in kt, Raten in ft/min, Abstände in m, Zeiten in UTC.

### 3.1 `geofences`

| Spalte | Bedeutung |
|---|---|
| `id` | bigserial |
| `name` | Anzeigename |
| `kind` | `circle` oder `polygon` |
| `geom` | `geometry(MultiPolygon, 4326)`; Kreise werden beim Laden in ein Polygon umgerechnet (geodätisch, 64 Stützpunkte) |
| `ref_point` | `geometry(Point, 4326)`: Bezugspunkt für den kleinsten Abstand. Bei Kreisen der Mittelpunkt, bei Polygonen die Feature-Property `ref_point`, sonst `ST_PointOnSurface(geom)` |
| `radius_m` | nur bei Kreisen |
| `relevance_max_alt_ft` | Relevanzgrenze, Standard 10000 |
| `source` | Herkunft und Lizenz, z. B. „OSM, ODbL, Abruf 2026-11-10“ |
| `valid_from`, `valid_to` | Gültigkeit; `valid_to IS NULL` = aktuelle Fassung |

Zonen werden über `name` identifiziert. Ändert sich Geometrie, Bezugspunkt oder Relevanzgrenze, wird die aktuelle Fassung mit `valid_to` geschlossen und eine neue angelegt. Ereignisse verweisen auf die Fassung, mit der sie berechnet wurden. Indizes: GiST auf `geom`, eindeutiger Teilindex auf `name WHERE valid_to IS NULL`.

### 3.2 `flights`

| Spalte | Bedeutung |
|---|---|
| `id` | bigserial |
| `icao24` | Transponderkennung |
| `callsign` | häufigster Wert im Flug |
| `first_ts`, `last_ts` | erste und letzte Position |
| `n_positions` | Anzahl verwendeter Positionen |
| `n_outliers` | verworfene Positionen |
| `track` | `geometry(LineStringM, 4326)`, M = Unix-Zeit in Sekunden |
| `analysis_run_id` | erzeugender Lauf |

Indizes: `(icao24, first_ts)`, GiST auf `track`, B-Tree auf `last_ts`.

### 3.3 `overflight_events`

| Spalte | Bedeutung |
|---|---|
| `id` | bigserial |
| `flight_id` | Fremdschlüssel auf `flights`, `ON DELETE CASCADE` |
| `geofence_id` | Fremdschlüssel auf die Zonenfassung |
| `entry_ts`, `exit_ts`, `duration_s` | Ein- und Austritt (interpoliert), Dauer |
| `min_dist_m`, `closest_ts` | kleinster horizontaler Abstand zu `ref_point` und Zeitpunkt |
| `min_alt_ft` | niedrigste barometrische Höhe innerhalb der Zone |
| `alt_at_closest_ft` | Höhe zum Zeitpunkt der größten Annäherung |
| `heading_deg`, `heading_sector` | Richtung über Grund zwischen Ein- und Austritt; Sektor N, NO, O, SO, S, SW, W, NW |
| `category` | `arrival`, `departure`, `overflight`, `unknown` |
| `category_basis` | jsonb: mittlere Vertikalrate, Abstandsänderung zu BER, Abstand zu BER, verwendete Schwellen |
| `relevant` | `min_alt_ft <= relevance_max_alt_ft` der Zonenfassung; bei fehlender Höhe `true` |
| `n_positions_inside`, `max_position_gap_s` | Datenqualität innerhalb der Zone |
| `in_reception_gap` | Durchquerung berührt eine Empfangslücke |
| `analysis_run_id` | erzeugender Lauf |

Verlässt ein Flug eine Zone und tritt erneut ein, entstehen zwei Ereignisse. Indizes: `(geofence_id, entry_ts)`, `flight_id`.

### 3.4 `analysis_runs`

`id`, `kind` (`incremental`, `rebuild`), `started_at`, `finished_at`, `algo_version`, `params` (jsonb: alle Schwellenwerte, BER-Referenzpunkt), `window_from`, `window_to`, `status` (`running`, `ok`, `failed`), `n_flights`, `n_events`, `n_skipped`, `error`. Das Wasserzeichen ergibt sich nur aus Läufen der Art `incremental`.

### 3.5 Views

- `overflights_daily`: je Tag (Europe/Berlin), Zone (Name), Kategorie und `relevant` die Anzahl der Ereignisse und die niedrigste Höhe.
- `data_coverage_daily`: je Tag und Empfänger der Anteil der Zeit mit Daten. Grundlage sind die eingelesenen `raw_files`-Zeiträume abzüglich der `reception_gaps`, soweit diese innerhalb der Dateizeiträume liegen (Neustart-Lücken liegen zwischen den Dateien und sind dort schon nicht enthalten).

### 3.6 Rollen

- Neu: `flightdb_analysis` (NOLOGIN in der Migration, LOGIN mit `DB_ANALYSIS_PASSWORD` im Init-Skript). Liest `positions`, `reception_gaps`, `raw_files`, `receivers`; schreibt `geofences`, `flights`, `overflight_events`, `analysis_runs`.
- `flightdb_reader` liest alle Tabellen und Views.
- `flightdb_ingest` bleibt unverändert.
- Für bestehende Installationen legt die Migration selbst keine Passwörter an. `docs/deployment-nas.md` beschreibt den einmaligen Schritt `ALTER ROLE flightdb_analysis LOGIN PASSWORD …`.

## 4. Dienst `analysis`

### 4.1 Aufbau (`analysis/src/analysis/`)

| Modul | Aufgabe |
|---|---|
| `config.py` | Umgebungsvariablen (siehe 4.5) |
| `logjson.py` | JSON-Logging wie in `ingest` |
| `zones.py` | GeoJSON einlesen und prüfen, Kreise umrechnen, mit `geofences` abgleichen und versionieren |
| `segment.py` | reine Logik: Positionen eines Flugzeugs → Flugabschnitte, Ausreißer |
| `events.py` | SQL: Durchquerungen und Kennwerte je Flug und Zone |
| `classify.py` | reine Logik: Kategorie und Begründung |
| `db.py` | Datenbankzugriffe. Migrationen spielt weiterhin allein `ingest` ein; `analysis` wartet, bis das Schema vorhanden ist |
| `pipeline.py` | Steuerung von Lauf und Neuberechnung |
| `cli.py`, `__main__.py` | Befehle |

### 4.2 Flugbildung (`segment.py`)

Eingabe: nach Zeit sortierte Positionen eines `icao24`. Ein neuer Flug beginnt, wenn

- zwischen zwei Positionen mehr als `ANALYSIS_FLIGHT_GAP_S` (Standard 600) liegen,
- sich das Rufzeichen ändert (beide Werte nicht leer), oder
- das Flugzeug nach `on_ground = true` wieder in der Luft ist.

Positionen am Boden gehören nicht in die Spur. Eine Position gilt als Ausreißer, wenn die Geschwindigkeit, die sich aus Abstand und Zeit zur letzten gültigen Position ergibt, `ANALYSIS_MAX_SPEED_KT` (Standard 800) übersteigt. Ausreißer werden verworfen und gezählt. Flüge mit weniger als 2 gültigen Positionen werden nicht gespeichert.

### 4.3 Ereignisse (`events.py`)

Für jeden neu gebildeten Flug und jede aktuelle Zonenfassung, deren `geom` die Spur schneidet:

1. `ST_Intersection(track, geom)` liefert ein oder mehrere Teilstücke; jedes ergibt ein Ereignis.
2. Ein- und Austritt sind M-Werte von Anfang und Ende des Teilstücks.
3. Kleinster Abstand: `ST_Distance` auf `geography` zwischen Teilstück und `ref_point`. Den Zeitpunkt liefert der M-Wert des nächstgelegenen Punkts (`ST_LineLocatePoint`, interpoliert).
4. Höhen und Datenqualität kommen aus den Positionen des Flugs mit `ts` zwischen Ein- und Austritt. Die an Ein- und Austritt interpolierten Höhen (aus den Nachbarpositionen) gehen immer in `min_alt_ft` ein. Liegt keine Position innerhalb, weil die Zone kleiner als der Positionsabstand ist, bestehen die Höhenwerte nur aus diesen interpolierten Werten und `n_positions_inside` ist 0.
5. Richtung: Azimut von Eintritts- zu Austrittspunkt.
6. `in_reception_gap`: Eine Lücke des Empfängers überschneidet `[entry_ts, exit_ts]`.

### 4.4 Einstufung (`classify.py`)

Grundlage sind die Positionen von `entry_ts − 120 s` bis `exit_ts + 120 s`.

| Kategorie | Bedingung |
|---|---|
| `unknown` | weniger als 5 Positionen mit Höhe, oder Steigen bei Annäherung bzw. Sinken bei Entfernung |
| `arrival` | mittlere Vertikalrate < −300 ft/min, Abstand zu BER nimmt ab, Abstand < 40 km |
| `departure` | mittlere Vertikalrate > +300 ft/min, Abstand zu BER nimmt zu, Abstand < 40 km |
| `overflight` | Betrag der Vertikalrate ≤ 300 ft/min oder Abstand ≥ 40 km |

Die Prüfung läuft in der Reihenfolge der Tabelle. Die Vertikalrate ist der Mittelwert von `baro_rate_fpm`; fehlt dieser, wird sie aus dem Höhenverlauf berechnet. Alle Schwellen sind konfigurierbar. Mehrdeutige Fälle wie Flüge zu anderen Plätzen oder Hubschrauber dürfen als `overflight` oder `unknown` erscheinen.

### 4.5 Konfiguration

`ANALYSIS_DB_DSN`, `ANALYSIS_INTERVAL_S` (300), `ANALYSIS_SETTLE_S` (120), `ANALYSIS_FLIGHT_GAP_S` (600), `ANALYSIS_MAX_SPEED_KT` (800), `ANALYSIS_CONTEXT_S` (120), `ANALYSIS_MIN_POSITIONS` (5), `ANALYSIS_VRATE_FPM` (300), `ANALYSIS_BER_RADIUS_M` (40000), `ANALYSIS_BER_LAT`, `ANALYSIS_BER_LON`, `ANALYSIS_ZONES_FILE`, `ANALYSIS_DEFAULT_RELEVANCE_FT` (10000). Im Container wird das Verzeichnis `config/local/` nur lesend eingebunden, die Zonendatei liegt dort als `geofences.geojson`. Der BER-Referenzpunkt steht nur in `nas/.env.example`, nicht im Code.

### 4.6 Laufsteuerung (`pipeline.py`)

Ein Lauf:

1. Obergrenze `window_to` = spätestes `period_end` der eingelesenen `raw_files` abzüglich `ANALYSIS_SETTLE_S` (Positionszeitpunkte liegen bis zu einer Minute vor dem Dateizeitraum). Ist eine registrierte, noch nicht eingelesene Datei (auch `failed`) früher, begrenzt ihr Beginn (aus dem Dateinamen) die Obergrenze; das wird je Lauf als Warnung protokolliert.
2. Untergrenze `window_from` = `window_to` des letzten Laufs mit `ok`. Beim ersten Lauf ist es die früheste Position.
3. Nachgelieferte Daten: Wurden seit Beginn des letzten erfolgreichen Laufs Dateien registriert (`fetched_at`) und eingelesen, deren `period_start < window_from` liegt, wird `window_from` auf deren frühesten `period_start` abzüglich `ANALYSIS_SETTLE_S` gesenkt.
4. Flüge mit `last_ts >= window_from − ANALYSIS_FLIGHT_GAP_S` werden samt Ereignissen gelöscht. Die Neubildung beginnt beim frühesten `first_ts` der gelöschten Flüge, sonst bei `window_from`.
5. Flugbildung und Ereignisse werden Flugzeug für Flugzeug aus den Positionen bis `window_to` berechnet. Auch Flüge, die noch andauern können, werden gespeichert; Schritt 4 des nächsten Laufs löscht und verlängert sie. Überflüge erscheinen so etwa eine Ingest-Periode nach dem Ereignis.
6. Alles in einer Transaktion, ein Sicherungspunkt je Flugzeug. Bei Fehlern Rollback und ein Eintrag `failed` in `analysis_runs`, der in einer eigenen Transaktion geschrieben wird.
7. Ein Advisory-Lock verhindert, dass `run` und `rebuild` gleichzeitig arbeiten.

Ist `window_to <= window_from` und gibt es keine Nachlieferung, endet der Lauf ohne Eintrag.

### 4.7 Befehle

| Befehl | Wirkung |
|---|---|
| `analysis run` | Dauerbetrieb: je Intervall Zonendatei abgleichen (falls konfiguriert), dann ein Lauf |
| `analysis once` | ein Lauf |
| `analysis rebuild --from --to` | Flüge, die den Zeitraum (± `ANALYSIS_FLIGHT_GAP_S`) berühren, löschen und neu berechnen, höchstens bis zum Wasserzeichen; Lauf der Art `rebuild` |
| `analysis zones [<datei>]` | Zonen laden und versionieren; gibt geänderte Zonen aus |
| `analysis health` | Heartbeat-Datei jünger als 3 × Intervall, letzter Lauf nicht `failed` und Wasserzeichen höchstens `ANALYSIS_MAX_LAG_S` (10800 s, drei Rotationen der Rohdateien) hinter dem Ende der eingelesenen Daten |

Zonenänderungen wirken nur auf neue Läufe. Für alte Zeiträume ist ein `rebuild` nötig. `analysis zones` weist darauf hin.

### 4.8 Fehlerbehandlung

- Keine aktuelle Zone oder ungültige GeoJSON: Der Lauf bricht mit klarer Meldung ab. Erfassung und Ingest sind nicht betroffen.
- Fehler bei einem einzelnen Flug, etwa ungültige Geometrie: Der Flug wird übersprungen, `n_skipped` erhöht und der Grund protokolliert.
- Datenbank nicht erreichbar: Der Lauf wird beim nächsten Intervall wiederholt.

## 5. Grafana

### 5.1 Betrieb

- Image `grafana/grafana` 13.2.6, per Digest gepinnt; Dienst `grafana` im Stack `nas/docker-compose.yml`, nur LAN, Port `${GRAFANA_LAN_PORT:-3001}`.
- Provisioning aus `dashboard/provisioning/`: Datenquelle PostGIS mit der Rolle `flightdb_reader`, Dashboards aus `dashboard/dashboards/*.json`.
- `.env`: `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_DATA_DIR`, `GRAFANA_LAN_PORT`.
- Abgeschaltet: anonymer Zugriff, Registrierung, Nutzungsstatistik, Update-Prüfung.

### 5.2 Dashboard „Überflüge“

Variablen: Zone, Kategorie, „nur relevante“ (Standard an), Zeitraum.

| Panel | Inhalt |
|---|---|
| Kennzahlen | Überflüge heute, 7 Tage, 30 Tage; niedrigste Höhe im Zeitraum; Empfangsabdeckung in % |
| Zeitverlauf | Überflüge pro Stunde/Tag/Woche/Monat, gestapelt nach Kategorie |
| Tageszeit | Heatmap Stunde × Wochentag |
| Höhen | Histogramm `min_alt_ft` |
| Richtung | Anteil je `heading_sector` |
| Kategorien | Anflug/Abflug/sonstig/unbekannt im Zeitverlauf, Hinweis „heuristisch“ |
| Tiefste Überflüge | Tabelle: Zeit, Rufzeichen, `icao24`, Höhe, Abstand, Kategorie, Datenqualität; Link auf die Spuransicht |
| Karte | Spuren und Positions-Heatmap des Zeitraums, darüber die Zonen |

Die Karte nutzt die Ansicht „Fit to data“. Kartenmittelpunkt und Zoom stehen nicht im Repo. Reicht das nicht, setzt der Betreiber den Startausschnitt lokal über die Grafana-Oberfläche. Diese Änderung wird nicht ins Repo zurückgespielt.

### 5.3 Dashboard „Datenqualität“

Empfangslücken, Dateien und Positionen je Stunde, Empfangsabdeckung je Tag, Uhrabweichung (`raw_files.clock_offset_max_s`), Status von `ingest_status`, letzter Analyse-Lauf mit Fehlern und übersprungenen Flügen, Dashboard-Link zu tar1090 über die Textvariable `tar1090`; die Adresse wird lokal in Grafana gespeichert, nicht im Repo.

### 5.4 Dashboard „Flugspur“

Variable `flight_id` (aus dem Link der Tabelle). Karte der Spur, Höhe und Geschwindigkeit über die Zeit, Ereignisse des Flugs.

## 6. Datenschutz im öffentlichen Repo

- Echte Zonen nur in `config/local/geofences.geojson` (gitignored). Im Repo liegt `config/geofences.example.geojson` mit erfundenen Formen im Atlantik.
- `scripts/osm_to_geofences.py` wandelt ein lokal heruntergeladenes Overpass-Ergebnis in das Zonenformat. `docs/analysis.md` beschreibt die Abfrage mit Platzhalter-Namen. Echte Ortsnamen stehen nur in der lokalen Abfrage.
- Synthetische Testspuren liegen über einem erfundenen Ort.
- Neues Prüfskript `scripts/check_dashboards.py`, auch in der CI: Es schlägt an, wenn ein Dashboard-JSON Kartenmittelpunkt, Zoom oder Koordinaten enthält.
- Der bestehende Pre-Commit-Hook bleibt aktiv.

## 7. Tests

| Ebene | Inhalt |
|---|---|
| Einheitentests | `segment` (Pause, Rufzeichenwechsel, Landung, Ausreißer, Flug über Dateigrenze), `classify` (alle Kategorien, Schwellen, `unknown`-Fälle), `zones` (Kreis → Polygon, ungültige Geometrie, Versionierung) |
| Datenbanktests | Gerader Überflug durch Kreiszone mit analytischen Sollwerten (Toleranz 1 s bzw. 25 m); Flug knapp neben der Zone ohne Ereignis; doppelte Durchquerung ergibt zwei Ereignisse; Empfangslücke setzt `in_reception_gap`; zwei Läufe ohne Duplikate; Nachlieferung löst Neuberechnung aus; `rebuild` reproduziert dieselben Ereignisse; `flightdb_analysis` darf nicht in `positions` schreiben |
| Dashboards | JSON wird aus `dashboard/build.py` erzeugt und ist aktuell; jede SQL-Abfrage läuft gegen die Test-Datenbank; `check_dashboards.py` |
| E2E | Bestehende Kette um `analysis` erweitert: synthetische Überflüge → erwartete Ereignisse |

## 8. Verzeichnisstruktur (neu in M3)

```text
analysis/
  Dockerfile
  src/analysis/        config, logjson, zones, segment, events, classify, db, pipeline, cli, __main__
config/
  geofences.example.geojson
dashboard/
  provisioning/        datasources/, dashboards/
  build.py             erzeugt die Dashboard-JSONs aus Panel-Definitionen
  dashboards/          ueberfluege.json, datenqualitaet.json, flugspur.json
database/migrations/
  002_analyse.sql
docs/
  analysis.md, dashboard.md
  decisions/0005-eigener-analyse-dienst.md, 0006-heuristische-einstufung.md
scripts/
  osm_to_geofences.py, check_dashboards.py
tests/
  analysis/, db/test_analysis_*.py
```

Geändert: `nas/docker-compose.yml`, `nas/.env.example`, `database/init/10-roles.sh`, `docs/data-model.md`, `docs/deployment-nas.md`, `README.md`, `pyproject.toml`, `.github/workflows/ci.yml`, `tests/e2e/`.

## 9. Abnahme

- **Ohne Hardware:** Alle Tests und die CI sind grün. Ein lokal gestartetes Grafana zeigt mit synthetischen Daten alle Panels mit plausiblen Werten.
- **Mit Hardware:** Nach einigen Tagen Betrieb werden Stichproben von Überflügen mit tar1090 bzw. Flightradar24 verglichen, nach Zeit, Rufzeichen, Höhe und Richtung.

## 10. Offene Punkte (blockieren die Entwicklung nicht)

- Echte Zonen: OSM-Abruf und Kreisradius um das Wohnumfeld legt der Betreiber lokal fest.
- Schwellenwerte der Einstufung werden nach den ersten realen Daten überprüft.
- Hardware-Abnahme von M2 steht noch aus.
