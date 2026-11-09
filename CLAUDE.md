# CLAUDE.md

## ⚠️ Öffentliches Repository

Dieses Repo ist **öffentlich** auf GitHub. Niemals committen:

- Wohnadresse, Koordinaten des Wohnorts oder des Empfängers, konkrete Geofence-Punkte
- Seriennummern, Hostnamen, interne IPs, MAC-Adressen der Infrastruktur
- Zugangsdaten, Tokens, API-Keys, Pushover-Keys, E-Mail-Adressen
- Screenshots, Logs, Rohdaten oder Exporte, die Rückschlüsse auf den Standort zulassen

Stattdessen:

- Echte Werte in `.env` bzw. `config/local/` (gitignored); im Repo nur `*.example` mit Platzhaltern
- Vor jedem Commit `git diff --cached` auf sensible Inhalte prüfen
- Commits und Pushes nur nach ausdrücklicher Freigabe

## Commits

- Autor ist ausschließlich der Repo-Inhaber. **Keine** `Co-Authored-By: Claude`-Zeilen, keine „Generated with Claude Code“-Hinweise in Commits oder PRs.

## Projekt

Projektübergabe liegt lokal in `writing-block.md` (gitignored, enthält Ortsangaben).
