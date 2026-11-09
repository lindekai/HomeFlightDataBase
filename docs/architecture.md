# Systemarchitektur

## Grundprinzip

Empfang und Verarbeitung sind räumlich getrennt:

- **Empfangsstation** (Raspberry Pi im Außenbereich): empfängt ADS-B auf 1090 MHz und schreibt Rohdaten lokal mit.
- **Zentrale** (Synology NAS im LAN): speichert, archiviert, analysiert und visualisiert.

## Komponenten

```text
[Hauswand]     1090-MHz-Antenne ─ Filter-LNA (Bias-Tee-versorgt)
                      │ ca. 5 m verlustarmes Koaxkabel
[Außenbereich] SDR ─ Raspberry Pi (wetterfestes Gehäuse)
                      ├─ readsb            Dekodierung der Mode-S/ADS-B-Nachrichten
                      ├─ tar1090           Live-Karte im LAN
                      └─ recorder          Rohdaten → stündliche Dateien (NDJSON.gz + SHA-256)
                      │ WLAN, Heimnetz
[NAS]          ingest                      holt abgeschlossene Dateien ab (Pull)
                      ├─ Rohdaten-Archiv   HDD-Volume, unverändert, mit Prüfsummen
                      ├─ PostGIS           SSD-Volume, normalisierte Daten
                      ├─ analysis          Überflüge, Geofences, Routenvergleich (Batch)
                      ├─ api               FastAPI, Exporte (CSV, GeoJSON, GPX)
                      ├─ grafana           Dashboards
                      └─ n8n (bestehend)   Orchestrierung, Berichte – nur lesender DB-Zugriff
```

## Datenfluss

1. `readsb` dekodiert die Signale des SDR.
2. `recorder` liest die Flugzeugzustände von `readsb` in kurzen Intervallen und schreibt sie unverändert als zeilenweises JSON in stündlich rotierende, komprimierte Dateien. Abgeschlossene Dateien erhalten eine SHA-256-Prüfsumme.
3. `ingest` auf dem NAS holt abgeschlossene Dateien ab, prüft die Prüfsumme, legt sie im Rohdaten-Archiv ab und lädt sie normalisiert in PostGIS.
4. Erst nach bestätigter Archivierung werden Dateien auf dem Pi zur Löschung freigegeben (konfigurierbare Vorhaltezeit).
5. `analysis` läuft zeitgesteuert als Batch und erzeugt Flüge, Überflugereignisse und Abweichungsbewertungen.
6. Grafana, API und n8n lesen ausschließlich aus PostGIS.

## Eigenschaften

| Anforderung | Umsetzung |
|---|---|
| Robust gegen WLAN-Ausfälle | Lokale Pufferung auf dem Pi, Pull durch das NAS |
| Nachvollziehbarkeit | Unveränderte Rohdaten + Prüfsummen; Datenbank jederzeit aus Rohdaten rekonstruierbar |
| Unabhängigkeit von n8n | Erfassung und Ingest laufen eigenständig; n8n orchestriert nur |
| Geringe CPU-Last (2 Kerne) | Batch-Inserts, Analysen zeitversetzt und sequenziell |
| Sicherheit | Keine öffentliche Erreichbarkeit; Dienste nur im LAN; Zugangsdaten nur in `.env` |
| Wiederanlauf | Docker Compose mit `restart: unless-stopped` und Healthchecks |

## Speicheraufteilung

| Daten | Speicherort | Begründung |
|---|---|---|
| PostGIS | SSD-Volume | viele kleine Schreibzugriffe, räumliche Indizes |
| Rohdaten-Archiv, Backups | HDD-Volume | groß, selten gelesen, komprimiert |

Grobe Abschätzung (vor Messung): Rohdaten-Archiv ca. 100–300 GB pro Jahr, Datenbank ca. 100–200 GB pro Jahr bei voller Auflösung. Wird nach Meilenstein 2 mit realen Werten überprüft.

## Weiterführend

- Datenmodell: [data-model.md](data-model.md)
- Deployment: [deployment-nas.md](deployment-nas.md), [deployment-receiver.md](deployment-receiver.md)
- Design Meilenstein 2: [superpowers/specs/2026-11-09-meilenstein-2-empfang-speicherung-design.md](superpowers/specs/2026-11-09-meilenstein-2-empfang-speicherung-design.md)

## Offene Punkte

- Modell des vorhandenen Raspberry Pi und Eignung vorhandener DVB-T-Sticks
- Abnahme Meilenstein 2 mit echter Hardware (7 Tage Dauerbetrieb, Speicherbedarf messen)
