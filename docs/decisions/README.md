# Architekturentscheidungen (ADR)

Jede wesentliche technische Entscheidung wird als kurze, nummerierte Datei dokumentiert: Kontext, Entscheidung, Konsequenzen.

| Nr. | Entscheidung | Status |
|---|---|---|
| [0001](0001-getrennte-empfangsstation.md) | Empfang und Verarbeitung räumlich getrennt | angenommen |
| [0002](0002-rohdaten-zuerst.md) | Rohdaten zuerst als Datei, dann Datenbank | angenommen |
| [0003](0003-pull-durch-nas.md) | NAS holt Daten vom Empfänger ab (Pull) | angenommen |
| [0004](0004-eigene-postgis-instanz.md) | Eigene PostGIS-Instanz, getrennt von n8n | angenommen |
| [0005](0005-eigener-analyse-dienst.md) | Eigener Analyse-Dienst | angenommen |
| [0006](0006-heuristische-einstufung.md) | Heuristische Einstufung Anflug/Abflug | angenommen |
| [0007](0007-zuordnung-zu-flugverfahren.md) | Zuordnung zu Flugverfahren in Stufen mit Sicherheitsstufe | angenommen |
