# 0001 – Empfang und Verarbeitung räumlich getrennt

**Status:** angenommen

## Kontext

Das NAS steht im Keller. ADS-B auf 1090 MHz breitet sich nahezu nur auf Sichtlinie aus; ein Kellerstandort ist für den Empfang ungeeignet.

## Entscheidung

Ein Raspberry Pi mit SDR arbeitet als eigenständige Empfangsstation im Außenbereich. Die Antenne wird erhöht an der Hauswand montiert. Das NAS übernimmt Speicherung, Analyse und Automatisierung.

## Konsequenzen

- Zwei Systeme müssen betrieben und überwacht werden.
- Die Verbindung erfolgt per WLAN; Ausfälle müssen abgefangen werden (siehe 0002, 0003).
- Die Empfangsstation braucht Wetterschutz.
