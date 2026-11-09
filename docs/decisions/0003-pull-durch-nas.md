# 0003 – NAS holt Daten vom Empfänger ab (Pull)

**Status:** angenommen

## Kontext

Der Empfänger ist per WLAN angebunden; Verbindungsabbrüche sind zu erwarten. Datenverluste würden Lücken in der Dokumentation erzeugen.

## Entscheidung

Abgeschlossene Rohdateien bleiben auf dem Pi, bis das NAS sie abgeholt, die Prüfsumme verifiziert und archiviert hat. Erst danach werden sie auf dem Pi nach einer konfigurierbaren Vorhaltezeit gelöscht.

## Konsequenzen

- WLAN-Ausfälle verzögern nur die Übertragung; Daten gehen nicht verloren, solange der Speicher auf dem Pi reicht.
- Der Pi benötigt ausreichend Speicher für mehrere Tage Puffer (SD-Karte mit hoher Schreibfestigkeit oder USB-SSD).
- Echte Empfangslücken (Empfänger aus, kein Signal) bleiben als solche erkennbar und werden protokolliert.
- Das NAS braucht einen Zugang zum Pi (z. B. SSH mit eigenem Schlüssel, nur lesend auf das Datenverzeichnis).
