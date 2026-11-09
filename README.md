# HomeFlightDataBase

Selbst gehostetes System zur Erfassung, Speicherung und Analyse von Flugbewegungen im Umfeld des Flughafens Berlin Brandenburg (BER/EDDB) mit einer eigenen ADS-B-Empfangsstation.

Ziel ist eine nachvollziehbare, statistisch belastbare Dokumentation von Überflügen über definierten Gebieten sowie der methodisch saubere Vergleich erfasster Flugspuren mit veröffentlichten Flugverfahren.

> **Hinweis:** Eine Abweichung von einer veröffentlichten Standardroute ist kein Nachweis eines Regelverstoßes. Radarführung und Direct-to-Freigaben der Flugsicherung sind aus ADS-B-Daten nicht erkennbar. Das System markiert Ereignisse nur zur manuellen Prüfung.

## Status

- Meilenstein 1 – Bestandsaufnahme und Architektur: abgeschlossen (offen: Prüfung der vorhandenen Empfangshardware)
- Meilenstein 2 – Empfang und Speicherung: Design abgestimmt, Umsetzungsplan in Arbeit

## Überblick

```text
Antenne ─ LNA ─ SDR ─ Raspberry Pi (readsb, recorder)
                              │  LAN/WLAN
                              ▼
                 NAS: ingest ─ PostGIS ─ Analyse ─ Grafana / API ─ n8n
```

Details: [docs/architecture.md](docs/architecture.md)

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Systemarchitektur und Datenfluss |
| [docs/hardware.md](docs/hardware.md) | Empfangshardware und Montage |
| [docs/decisions/](docs/decisions/) | Architekturentscheidungen (ADR) |
| [docs/superpowers/specs/](docs/superpowers/specs/) | Designspezifikationen je Meilenstein |

## Meilensteine

1. Bestandsaufnahme und Architektur
2. Empfang und Speicherung
3. Geofences und Dashboard
4. Flugroutenvergleich
5. Berichte und n8n-Automatisierung
6. Qualitätssicherung

## Konfiguration und Datenschutz

Standortbezogene Werte (Koordinaten, Geofences), Zugangsdaten und erfasste Daten werden **nicht** versioniert. Konfiguration erfolgt über `.env`-Dateien (Vorlagen: [nas/.env.example](nas/.env.example), [receiver/.env.example](receiver/.env.example)) und `config/local/`.
