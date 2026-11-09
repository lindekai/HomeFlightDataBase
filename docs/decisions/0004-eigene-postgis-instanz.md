# 0004 – Eigene PostGIS-Instanz, getrennt von n8n

**Status:** angenommen

## Kontext

Auf dem NAS läuft bereits produktiv n8n mit eigener Postgres-Datenbank. Das Projekt benötigt PostGIS und eigene Aufbewahrungs- und Backupregeln.

## Entscheidung

Das Projekt betreibt eine eigene PostGIS-Instanz in einem eigenen Container auf dem SSD-Volume. Die n8n-Datenbank und der n8n-Container bleiben unverändert. n8n greift über eine eigene, nur lesende Datenbankrolle auf die Projektdatenbank zu.

## Konsequenzen

- Kein Risiko für den produktiven n8n-Betrieb.
- Unabhängige Updates, Backups und Aufbewahrungsfristen.
- Zusätzlicher RAM-Bedarf von einigen hundert MB (bei 16 GB unkritisch).
- In n8n ist nur ein zusätzlicher Postgres-Credential-Eintrag nötig.
