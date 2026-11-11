# 0005 – Eigener Analyse-Dienst

**Status:** angenommen

## Kontext

Aus den Positionen sollen Flüge und Überflugereignisse entstehen. Möglich wären eine Auswertung im
Ingest-Prozess, reines SQL in PostGIS oder ein eigener Dienst.

## Entscheidung

Ein eigener Dienst `analysis` (Python) bildet Flüge und steuert die Läufe; Schnittmengen, Abstände
und Interpolation rechnet PostGIS. Jeder Lauf wird mit Version und Parametern in `analysis_runs`
protokolliert. Migrationen spielt weiterhin nur `ingest` ein.

## Konsequenzen

- Fehler in der Auswertung beeinträchtigen Erfassung und Quittierung nicht.
- Auswertungen sind reproduzierbar und mit `rebuild` neu berechenbar.
- Ein zusätzlicher Container; geringe Last durch inkrementelle Läufe.
