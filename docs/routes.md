# Flugroutenvergleich

Der Dienst `analysis` vergleicht An- und Abflüge mit den veröffentlichten Abflug- und
Anflugverfahren (SID/STAR) von BER. Jeder Flug mit Rolle erhält eine Bewertung in
`flight_assessments` mit Zuordnungssicherheit, Begründung und Datenqualität.

> **Eine Abweichung ist kein Verstoß.** Radarführung und individuelle Freigaben der Flugsicherung
> sind zulässig und aus ADS-B-Daten nicht erkennbar. Eine statistisch typische Spur ist kein
> veröffentlichtes Verfahren. Markierte Flüge sind Fälle zur manuellen Prüfung.

## Verfahrensdatei

Ort: `config/local/procedures.yaml` (gitignored; im NAS-Stack `/zones/procedures.yaml`).
Vorlage mit erfundenem Flughafen im Atlantik: `config/procedures.example.yaml`.

| Abschnitt | Inhalt |
|---|---|
| `source` | Quelle, frei (erscheint in `procedures.source`), z. B. „DFS AIP Germany, AD 2 EDDB, AIRAC 2611“ |
| `waypoints` | Name → Koordinate, `"GG MM SS.ssN GGG MM SS.ssE"` wie in der AIP oder `[lat, lon]` |
| `runways` | Bezeichnung in Anführungszeichen (`"25R"`) → Schwelle; zu jeder Bahn auch die Gegenrichtung |
| `procedures` | je Verfahren `name`, `kind` (`SID`/`STAR`), `runway`, `valid_from`, `valid_to` (`null` = offen), `airac`, `route` (Wegpunktfolge), optional `constraints` (nur Anzeige) |

Geometrie: Eine SID beginnt an der Schwelle der Gegenrichtung (Abflugende der Bahn, für `25R`
die Schwelle `07L`) und führt über die Wegpunkte; eine STAR verbindet nur ihre Wegpunkte, ohne
Endanflug. Die Betriebsrichtung eines Verfahrens folgt aus dem Kurs der Startbahn (Schwelle →
Gegenschwelle): 180–359° `west`, 0–179° `east`. Der Sektor (`N`, `NO`, …) ist die Richtung vom
BER-Referenzpunkt zu dem Punkt, an dem die Linie den BER-Radius verlässt (SID) bzw. betritt
(STAR).

Die Datei wird als Ganzes abgelehnt – die bisherige Fassung bleibt aktiv –, wenn ein Wegpunkt
oder eine Startbahn unbekannt ist, eine Koordinate unlesbar oder außerhalb ±90/±180 liegt, ein
Wegpunkt weiter als 200 km vom Referenzpunkt entfernt ist, ein Name doppelt vorkommt (Verfahren:
bei überlappender Gültigkeit), eine SID keinen bzw. eine STAR weniger als zwei Wegpunkte hat oder
`valid_to` vor `valid_from` liegt. Meldungen nennen Eintrag und Feld, nie Koordinaten.

Ändert sich ein Verfahren (gleicher Name, gleicher `valid_from`), entsteht eine neue Fassung; die
alte erhält `superseded_at`. Verfahren, die aus der Datei entfernt werden, werden ebenso
geschlossen.

## Übertragen aus der AIP

Quelle ist die veröffentlichte AIP Germany der DFS (Teil AD 2, Flugplatz EDDB). Abschnittsnummern
und Kartentitel können sich mit neuen Ausgaben ändern; maßgeblich ist die gültige Ausgabe.

| Angabe in der Datei | Fundstelle (in der Regel) |
|---|---|
| Schwellen (`runways`) | AD 2 EDDB, Abschnitt zu den Start- und Landebahnen (AD 2.12, Spalte mit den Schwellenkoordinaten) |
| Verfahren, Startbahn, Wegpunktfolge | SID- und STAR-Karten von EDDB mit den zugehörigen Streckenbeschreibungen |
| Wegpunktkoordinaten | Wegpunkttabellen auf bzw. zu den Karten; sonst ENR 4.4 (wichtige Punkte) |
| `valid_from`, `airac` | Beginn des AIRAC-Zyklus, ab dem die Seiten gelten |
| `constraints` | Höhen- und Geschwindigkeitsangaben der Karten (nur zur Anzeige) |

Vorgehen:

1. Gültige AIRAC-Ausgabe wählen und `source` mit Ausgabe und Zyklus füllen.
2. Schwellen beider Richtungen und alle benötigten Wegpunkte übertragen; Koordinaten wörtlich
   aus der AIP abschreiben (Grad, Minuten, Sekunden).
3. Je Verfahren die Wegpunktfolge vom ersten Wegpunkt nach dem Abflug bzw. bis zum letzten
   Wegpunkt vor dem Endanflug eintragen.
4. Prüfen: `python scripts/check_procedures.py config/local/procedures.yaml` (Referenzpunkt aus
   `ANALYSIS_BER_LAT`/`ANALYSIS_BER_LON` oder `--ber-lat`/`--ber-lon`). Die Ausgabe nennt je
   Verfahren Art, Bahn, Richtung, Sektor, Gültigkeit und Länge; unplausible Sektoren oder Längen
   deuten auf Übertragungsfehler hin.
5. Optional die Linien lokal in QGIS gegen die Karte prüfen (Datei nicht auf fremde Seiten laden).
6. Laden: `sudo docker compose exec analysis python -m analysis procedures`.

Bei einem AIRAC-Wechsel geänderte Verfahren mit neuem `valid_from` als neuen Eintrag anlegen und
beim bisherigen `valid_to` setzen. Für einen Flug gilt die nicht abgelöste Fassung, deren
Gültigkeit das UTC-Datum des Flugbeginns enthält.

## Methodik

Gerechnet wird in einer lokalen mittabstandstreuen Ebene um den BER-Referenzpunkt; im Umkreis von
100 km ist der Fehler gegenüber der Korridorbreite vernachlässigbar.

### Rolle

Betrachtet wird der Teil der Spur innerhalb von `ANALYSIS_BER_RADIUS_M`. **Abflug:** Der Teil
beginnt näher als `ANALYSIS_ROLE_NEAR_M` (10 km) am Referenzpunkt unterhalb
`ANALYSIS_ROLE_MAX_ALT_FT` (3000 ft) und steigt im Mittel stärker als `ANALYSIS_VRATE_FPM`.
**Anflug:** spiegelbildlich am Ende des Teils mit Sinken. Andere Flüge erhalten keine Bewertung.

### Betriebsrichtung

Bezugskurs eines Flugs ist der Kurs zwischen den Spurpunkten am Rand von 10 km und bei
`ANALYSIS_DIRECTION_DIST_M` (15 km), bei Abflügen am Anfang, bei Anflügen am Ende. Weicht er
höchstens `ANALYSIS_DIRECTION_TOL_DEG` (30°) vom nächsten Startbahnkurs ab, stimmt der Flug für
dessen Richtung. Je 30-Minuten-Fenster (UTC) gilt die Mehrheit, wenn mindestens
`ANALYSIS_DIRECTION_MIN_FLIGHTS` (3) Stimmen vorliegen und ihr Anteil mindestens
`ANALYSIS_DIRECTION_MIN_SHARE` (0,8) beträgt; sonst `unknown`. Kommen Flüge nach, werden die
betroffenen Fenster und die Flüge darin neu bewertet.

### Zuordnung

1. Kandidaten: gültige Verfahren passender Art (SID ↔ Abflug, STAR ↔ Anflug) und – wenn bekannt –
   passender Betriebsrichtung.
2. Sektor: gleicher Sektor „passt genau“, Nachbarsektor „passt ungefähr“, sonst ausgeschlossen.
3. Geometrie: mittlerer seitlicher Abstand der Positionen im Geltungsabschnitt zur Ideallinie;
   das kleinste Mittel gewinnt.
4. Sicherheit: `high`, wenn die Richtung bekannt ist, der Sektor genau passt und das zweitbeste
   Verfahren mindestens `ANALYSIS_ASSIGN_RATIO` (2,0) mal so weit entfernt ist (oder keines in
   Frage kommt); `medium`, wenn genau eine dieser Bedingungen fehlt; `low` bei mehreren; `none`
   ohne Kandidat.

Die Begründung (`basis`) nennt je Prüfung einen Satz.

### Abweichung (C)

Geltungsabschnitt sind die Positionen, deren Lotfußpunkt zwischen Anfang und Ende der Ideallinie
liegt, bei gesetztem `ANALYSIS_ROUTE_MAX_ALT_FT` nur bis zu dieser Höhe. Bewertet wird nur bei
Sicherheit `high` oder `medium`. Der Korridor hat die halbe Breite `ANALYSIS_CORRIDOR_M`
(1852 m = 1 NM). Außerhalb-Abschnitte entstehen aus aufeinanderfolgenden Positionen, Ein- und
Austritt werden linear interpoliert. `deviation` gilt, wenn ein Abschnitt mindestens
`ANALYSIS_CORRIDOR_MIN_S` (30 s) dauert; kurze Überschwinger zählen nur in `outside_s`.

### Annäherung (B)

Für jede aktuelle Zone wird der kleinste Abstand der Spur (im Geltungsabschnitt) und der
Ideallinie zum Zonen-Referenzpunkt bestimmt. Maßgeblich ist die Zone mit der kleinsten Differenz
Spur − Ideallinie. `approach` gilt, wenn die Spur mehr als `ANALYSIS_APPROACH_TOL_M` (Standard
wie der Korridor) näher kommt als die Ideallinie.

### Prüffall (E)

Ein Flug ist Prüffall, wenn alle Bedingungen gelten: Abweichung oder Annäherung; Sicherheit
`high` oder `medium`; keine Empfangslücke im bewerteten Abschnitt und größte Positionslücke
höchstens `ANALYSIS_REVIEW_MAX_GAP_S` (30 s); mindestens ein relevanter Überflug des Flugs.
`review_reasons` listet die erfüllten Bedingungen.

## Grenzen

- Die Ideallinie verbindet Schwelle und Wegpunkte geradlinig. Kurvenradien, Überflug- oder
  Vorbeiflugwegpunkte, Bögen, Warteschleifen sowie Höhen- und Geschwindigkeitsvorgaben sind nicht
  modelliert; eine STAR endet am letzten Wegpunkt vor dem Endanflug.
- Radarführung und Direktfreigaben erscheinen als Abweichung; Kategorie D (auffällige
  Flugführung) folgt später.
- Ohne Empfang nahe BER in geringer Höhe fällt die Rolle aus und es entstehen keine Bewertungen
  (zeigt erst die Abnahme mit Hardware).
- Bei wenig Verkehr (z. B. nachts) bleibt die Betriebsrichtung oft `unknown`; Zuordnungen sind
  dann höchstens `medium`.
- Flüge nahe einer Sektorgrenze können in den Nachbarsektor fallen („passt ungefähr“).
- `rebuild` verwendet die aktuell nicht abgelösten Fassungen der Verfahren.
- Fehlte die Verfahrensdatei bei einigen Läufen, erhalten die in dieser Zeit gebildeten Flüge
  keine Bewertung, und Flüge, die diese Läufe neu gebildet haben, verlieren ihre Bewertung
  (Löschung kaskadiert); die Betriebsrichtung dieser Fenster bleibt veraltet. Nach der
  Rückkehr der Datei den Zeitraum mit `analysis rebuild` neu berechnen.
- Der Wert für `ANALYSIS_ROUTE_MAX_ALT_FT` ist noch aus der AIP bzw. aus Veröffentlichungen zur
  Radarführung abzuleiten; bis dahin wird ohne Höhengrenze verglichen.
- Die Karte im Dashboard zeigt den Korridor als Randlinie aus Punkten im Abstand von 200 m, weil
  Grafana aus SQL keine Flächen zeichnet.

## Urheberrecht

Inhalte der AIP unterliegen dem Urheberrecht der DFS Deutsche Flugsicherung GmbH. Die
übertragene Datei bleibt lokal in `config/local/` und wird nicht veröffentlicht; das Repository
enthält nur erfundene Beispiele.
