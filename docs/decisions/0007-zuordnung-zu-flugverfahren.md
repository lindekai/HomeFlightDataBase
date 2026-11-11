# 0007 – Zuordnung zu Flugverfahren in Stufen

**Status:** angenommen

## Kontext

Flugspuren sollen mit veröffentlichten Abflug- und Anflugverfahren verglichen werden. Die
Flugsicherung führt Flüge oft per Radar oder gibt Direktfreigaben; welches Verfahren ein Flug
erhalten hat, ist aus ADS-B nicht erkennbar. Eine reine Suche nach der nächstgelegenen Linie
würde bei parallelen oder sich überlagernden Verfahren und bei wechselnder Betriebsrichtung
falsche, aber scheinbar sichere Zuordnungen liefern.

## Entscheidung

Die Zuordnung erfolgt in Stufen: zuerst Rolle (Abflug/Anflug) und Betriebsrichtung je
30-Minuten-Fenster aus den Kursen aller Flüge, dann Kandidaten nach Art, Richtung und Sektor,
zuletzt die Geometrie (mittlerer seitlicher Abstand zur Ideallinie). Jede Zuordnung erhält eine
Sicherheitsstufe (`high`, `medium`, `low`, `none`) nach der Zahl nicht erfüllter Bedingungen und
eine Begründung je Prüfung. Abweichung, Annäherung und Prüffall werden nur bei `high` oder
`medium` bewertet. Verfahren werden von Hand aus der AIP in eine lokale Datei übertragen und
versioniert gespeichert.

## Konsequenzen

- Jede Bewertung ist nachvollziehbar: Richtung, Sektor und Abstände stehen in der Begründung.
- Unsichere Fälle werden ausgewiesen statt bewertet; der Anteil bewertbarer Flüge ist eine
  eigene Kennzahl.
- Die Methode hängt von der Sicht des Empfängers nahe BER ab und modelliert keine Kurvenradien.
- Neue AIRAC-Zyklen erfordern eine manuelle Pflege der Verfahrensdatei.
