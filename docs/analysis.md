# Auswertung: Flüge und Überflüge

Dienst `analysis` auf dem NAS (Rolle `flightdb_analysis`). Er liest `positions` und schreibt
`flights`, `overflight_events` und `analysis_runs`. Erfassung und Ingest laufen unabhängig davon.

## Ablauf eines Laufs

1. Zonendatei abgleichen (`ANALYSIS_ZONES_FILE`): geänderte Zonen erhalten eine neue Fassung.
2. Zeitfenster: bis zum Ende der eingelesenen Rohdateien abzüglich `ANALYSIS_SETTLE_S`; ab dem
   Ende des letzten erfolgreichen Laufs. Nachgelieferte ältere Dateien verschieben den Beginn nach
   vorn.
3. Flüge, die bis an das Fenster heranreichen, werden gelöscht und ab ihrem Beginn neu gebildet.
   Dadurch erscheinen Überflüge etwa eine Ingest-Periode nach dem Ereignis.
4. Flugbildung, Zonendurchquerungen, Kennwerte und Einstufung; alles in einer Transaktion.

## Fehlerbehandlung und Betrieb

Jeder Fehler bei einem einzelnen Flugzeug wird per Savepoint zurückgerollt, protokolliert und als
übersprungen gezählt (`skipped`); der Lauf wird mit den übrigen Flugzeugen fortgesetzt. Nur ein
Verbindungsabbruch zur Datenbank (`OperationalError`) bricht den Lauf ab.

Fehlen Zonendatei oder Schema, protokolliert `run` den Fehler bei jedem Intervall und setzt keinen
Heartbeat. Der Container wird nach rund 3 Intervallen „unhealthy“ und erholt sich selbst, sobald
die Ursache behoben ist.

Eine registrierte, aber nicht eingelesene Rohdatei (auch Status `failed`) begrenzt das Zeitfenster
auf ihren Beginn. Solange das so ist, protokolliert jeder Lauf eine Warnung mit Dateipfad, Status,
Dateibeginn und Wartezeit seit der Registrierung. `health` meldet „unhealthy“, wenn das
Wasserzeichen (Fensterende des letzten erfolgreichen inkrementellen Laufs) mehr als
`ANALYSIS_MAX_LAG_S` hinter dem Ende der eingelesenen Daten liegt. Ein abgeschalteter Empfänger
löst das nicht aus, weil dann auch keine neueren Daten eingelesen werden. Die Ursache steht in
`raw_files.error` und im Log von `ingest`.

## Flugbildung

Neuer Flug nach einer Pause von mehr als `ANALYSIS_FLIGHT_GAP_S` (600 s), bei Wechsel des
Rufzeichens oder nach einer Landung. Positionen am Boden gehören nicht zur Spur. Positionen, die
nur mit mehr als `ANALYSIS_MAX_SPEED_KT` (800 kt) erreichbar wären, gelten als Ausreißer.

## Überflugereignisse

Jedes Teilstück der Spur innerhalb einer Zone ist ein Ereignis. Ein- und Austritt werden auf der
Spur interpoliert. Der kleinste Abstand bezieht sich auf den Bezugspunkt der Zone (Kreismittelpunkt
bzw. `ref_point`). Die niedrigste Höhe (`min_alt_ft`) ist die barometrische Höhe
(Standardatmosphäre), **nicht** die Höhe über Grund. Sie berücksichtigt die Positionen innerhalb
der Zone **und** die an Ein- und Austritt interpolierten Höhen. Liegt keine Position innerhalb der
Zone, stammen die Höhenwerte nur aus den interpolierten Werten und `n_positions_inside` ist 0.

Datenqualität je Ereignis: Positionen in der Zone, größte Lücke zwischen Positionen, Überschneidung
mit einer Empfangslücke.

## Einstufung (heuristisch)

| Kategorie | Bedingung |
|---|---|
| `unknown` | weniger als 5 Positionen mit Höhe oder, innerhalb 40 km um BER, Höhenverlauf widerspricht Abstandsänderung |
| `arrival` | sinkt stärker als 300 ft/min, nähert sich BER, Abstand < 40 km |
| `departure` | steigt stärker als 300 ft/min, entfernt sich von BER, Abstand < 40 km |
| `overflight` | alle übrigen Fälle |

Grundlage sind die Positionen in der Zone plus je 120 s davor und danach. Als Abstand zu BER gilt
der kleinere Abstand von Anfang und Ende des betrachteten Ausschnitts. Die Begründung steht in
`category_basis`. Die Einstufung ist **keine** Zuordnung zu einem Flugverfahren; Flüge zu anderen
Plätzen oder Hubschrauber können als `overflight` oder `unknown` erscheinen.

## Parameter

| Variable | Standard | Bedeutung |
|---|---|---|
| `ANALYSIS_INTERVAL_S` | 300 | Abstand der Läufe |
| `ANALYSIS_SETTLE_S` | 120 | Sicherheitsabstand zum Ende der Rohdaten |
| `ANALYSIS_FLIGHT_GAP_S` | 600 | Pause, nach der ein neuer Flug beginnt |
| `ANALYSIS_MAX_SPEED_KT` | 800 | Grenze für Ausreißer |
| `ANALYSIS_CONTEXT_S` | 120 | Kontext für die Einstufung |
| `ANALYSIS_MIN_POSITIONS` | 5 | Mindestzahl für eine Einstufung |
| `ANALYSIS_VRATE_FPM` | 300 | Schwelle Steigen/Sinken |
| `ANALYSIS_BER_RADIUS_M` | 40000 | Umkreis um BER für Anflug/Abflug |
| `ANALYSIS_BER_LAT`, `ANALYSIS_BER_LON` | – | Flughafen-Referenzpunkt |
| `ANALYSIS_DEFAULT_RELEVANCE_FT` | 10000 | Relevanzgrenze, wenn die Zone keine angibt |
| `ANALYSIS_MAX_LAG_S` | 10800 | Höchster Rückstand des Wasserzeichens für `health` (drei Rotationen der Rohdateien, damit eine frisch eingelesene Stundendatei vor dem nächsten Lauf keinen Fehlalarm auslöst) |

Alle ergebnisrelevanten Parameter eines Laufs stehen in `analysis_runs.params`.

## Zonendatei

`config/local/geofences.geojson` (gitignored), Vorlage: `config/geofences.example.geojson`.

- Kreis: `Point` + `radius_m`
- Polygon: `Polygon` oder `MultiPolygon`, optional `ref_point: [lon, lat]`
- immer: `name` (eindeutig); optional `relevance_max_alt_ft`, `source`

### Ortsteil- und Gemeindegrenzen aus OpenStreetMap

1. Abfrage lokal anlegen, z. B. `config/local/overpass.overpassql` (Namen einsetzen):

   ```text
   [out:json][timeout:90];
   area["name"="<Landkreis>"]["boundary"="administrative"]->.a;
   relation(area.a)["boundary"="administrative"]["name"~"^(<Gemeinde>|<Ortsteil 1>|<Ortsteil 2>)$"];
   out geom;
   ```

2. Abrufen: `curl -s --data-urlencode data@config/local/overpass.overpassql https://overpass-api.de/api/interpreter > config/local/overpass.json`
3. Umwandeln (Kreis um das Wohnumfeld ergänzen):

   ```bash
   python scripts/osm_to_geofences.py config/local/overpass.json \
     --source "OSM, ODbL, Abruf JJJJ-MM-TT" --circle "Nahbereich,<lat>,<lon>,<radius_m>" \
     > config/local/geofences.geojson
   ```

4. Ergebnis lokal prüfen, z. B. in QGIS (Datei als Vektorlayer öffnen), dann `analysis zones`.
   Die Datei nicht auf fremde Webseiten hochladen: Die Zonen beschreiben das Wohnumfeld.

Ortsteile sind in OSM teils mit anderem `admin_level` oder als `boundary=place` erfasst; dann die
Abfrage anpassen. Die Overpass-Server sehen die abgefragten Namen.

## Befehle

```bash
sudo docker compose exec analysis python -m analysis zones            # Zonen laden
sudo docker compose exec analysis python -m analysis once             # ein Lauf
sudo docker compose exec analysis python -m analysis rebuild --from 2026-11-01 --to 2026-12-01
```

Zonenänderungen wirken nur auf neue Läufe; für zurückliegende Zeiträume `rebuild` ausführen.
