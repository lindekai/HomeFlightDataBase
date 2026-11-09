# 0002 – Rohdaten zuerst als Datei, dann Datenbank

**Status:** angenommen

## Kontext

Beweissicherung und Nachvollziehbarkeit sind ein Schwerpunkt. Analysen und Normalisierung werden sich im Projektverlauf ändern.

## Entscheidung

Der Empfänger schreibt die von `readsb` gelieferten Daten unverändert als zeilenweises JSON in stündlich rotierende, komprimierte Dateien. Jede abgeschlossene Datei erhält eine SHA-256-Prüfsumme. Diese Dateien werden unverändert archiviert; die Datenbank enthält nur daraus abgeleitete, normalisierte Daten.

## Konsequenzen

- Die Datenbank ist jederzeit aus den Rohdaten neu aufbaubar, auch mit geänderter Analyse-Software.
- Jeder Datensatz in der Datenbank ist auf eine Rohdatei samt Prüfsumme zurückführbar.
- Zusätzlicher Speicherbedarf für das Archiv (komprimiert, auf HDD).
- Daten erreichen die Datenbank mit Verzögerung (bis zu einer Rotationsperiode). Die Live-Ansicht erfolgt deshalb über `tar1090` direkt auf dem Pi.
