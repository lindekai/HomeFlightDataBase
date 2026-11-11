# 0006 – Heuristische Einstufung Anflug/Abflug

**Status:** angenommen

## Kontext

Die Unterscheidung von Anflügen und Abflügen ist für die Statistik wichtig. Eine belastbare
Zuordnung zu Bahn und Verfahren ist erst mit Referenzrouten (Meilenstein 4) möglich.

## Entscheidung

Bis dahin wird jedes Ereignis aus Höhenverlauf und Abstandsänderung zum Flughafen-Referenzpunkt
als `arrival`, `departure`, `overflight` oder `unknown` eingestuft. Die Begründung wird mit
gespeichert; unklare Fälle bleiben `unknown`. Dashboards kennzeichnen die Einstufung als
heuristisch.

## Konsequenzen

- Sofort nutzbare Aufteilung der Überflüge.
- Fehleinstufungen sind möglich und nachvollziehbar; sie sind kein Nachweis eines Verfahrens.
- Meilenstein 4 kann die Einstufung ersetzen, ohne das Schema umzubauen.
