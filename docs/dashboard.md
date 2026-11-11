# Dashboards (Grafana)

Grafana läuft im NAS-Stack, nur im LAN (`http://<NAS>:${GRAFANA_LAN_PORT}`), Anmeldung mit
`admin` und `GRAFANA_ADMIN_PASSWORD`. Grafana liest ausschließlich über `flightdb_reader`.

| Dashboard | Inhalt |
|---|---|
| Überflüge | Kennzahlen, Zeitverlauf nach Kategorie, Tageszeit × Wochentag, Höhen, Richtungen, tiefste Überflüge, Karte mit Spuren und Zonen |
| Datenqualität | Empfangsabdeckung, Positionen und Dateien je Stunde, Uhrabweichung, Lücken, Ingest- und Analysestatus, Link zur Live-Karte |
| Flugspur | Spur, Höhe und Geschwindigkeit, Überflüge eines Flugs (Link aus der Tabelle „Tiefste Überflüge“) |

Filter „Überflüge: relevante“ zeigt nur Ereignisse unterhalb der Relevanzgrenze der Zone.
Kategorien sind heuristisch (siehe [analysis.md](analysis.md)).

## Änderungen

Dashboards werden aus `dashboard/build_dashboards.py` erzeugt:

```bash
python dashboard/build_dashboards.py
python scripts/check_dashboards.py dashboard/dashboards/*.json
```

In der Oberfläche gespeicherte Änderungen bleiben in der Grafana-Datenbank, bis sich die Datei im
Repo ändert. Dauerhafte Änderungen gehören in den Generator.

## Datenschutz

- Karten nutzen „Fit to data“; Kartenmittelpunkt und Zoom stehen nicht im Repo.
- Die tar1090-Adresse wird als Variable `tar1090` im Dashboard „Datenqualität“ eingetragen und
  in Grafana gespeichert, nicht im Repo.
- Die Hintergrundkarte lädt Kacheln von einem externen Anbieter; dieser sieht den betrachteten
  Kartenausschnitt.
- CSV-Export von Tabellen: Panel-Menü → *Inspect* → *Data*. Exporte nicht ins Repo legen.
