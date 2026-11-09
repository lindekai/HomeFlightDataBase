# Hardware

## Empfangsstation

| Komponente | Empfehlung | Status |
|---|---|---|
| Kleincomputer | Raspberry Pi 3B+, 4 oder 5 | vorhanden, Modell zu prüfen |
| SDR | RTL-SDR Blog V4 | vorhandene DVB-T-Sticks werden zuerst geprüft |
| Vorverstärker | gefilterter 1090-MHz-LNA, an der Antenne montiert | anzuschaffen |
| Antenne | 1090-MHz-Kollinearantenne für den Außeneinsatz | anzuschaffen |
| Kabel | ca. 5 m LMR-400 oder Aircell 7, N-Stecker | anzuschaffen |
| Gehäuse | IP65 mit Druckausgleich, Kabelverschraubungen | anzuschaffen |
| Netzteil | offizielles Pi-Netzteil passend zum Modell | zu prüfen |

Preise und Verfügbarkeit werden vor einer Bestellung aktuell geprüft.

## Begründungen

### SDR

- **RTL-SDR Blog V4:** integrierte, softwareseitig schaltbare Bias-Tee zur Versorgung des LNA über das Koaxkabel; von `readsb` unterstützt (aktueller `librtlsdr` erforderlich).
- **FlightAware Pro Stick Plus:** gut geeignet bei sehr kurzem Kabel. Hier nicht empfohlen, da Verstärker und Filter am Stick – also *nach* dem 5-m-Kabel – sitzen und die Kabelverluste nicht ausgleichen.

### Vorverstärker an der Antenne

Ein LNA direkt an der Antenne legt das Rauschmaß des Systems vor das Kabel und macht dessen Dämpfung weitgehend bedeutungslos. Das integrierte Bandpassfilter unterdrückt Mobilfunk und lokale Störquellen.

### Kabeldämpfung bei 1090 MHz (Richtwerte)

| Kabel | Dämpfung | auf 5 m |
|---|---|---|
| RG-58 | ~0,6 dB/m | ~3 dB – nicht empfohlen |
| LMR-240 | ~0,4 dB/m | ~2 dB |
| LMR-400 / Aircell 7 | ~0,22 dB/m | ~1,1 dB – empfohlen |

Zusätzlich ca. 0,1–0,3 dB je Steckverbindung.

## Prüfung vorhandener DVB-T-Sticks

Gewöhnliche USB-Speichersticks sind keine SDR. Geeignet sind nur DVB-T-Sticks mit Realtek-RTL2832U-Chip, idealerweise mit R820T/R820T2-Tuner.

Auf dem Pi ausführen:

```bash
cat /proc/device-tree/model; echo; lsusb
```

Ein geeigneter Stick erscheint typischerweise als `0bda:2838` oder `0bda:2832` (Realtek RTL2838/RTL2832). Ältere Tuner (E4000, FC0012/13) sind für 1090 MHz kaum brauchbar.

## Montagehinweise

- Antenne möglichst hoch und mit freier Sicht zum Horizont, insbesondere Richtung Flughafen.
- Antenne mit Abstand zu Pumpen, Motoren und deren Steuerungen (elektromagnetische Störungen).
- Gehäuse vor direkter Sonneneinstrahlung schützen; Feuchtigkeit und korrosive Dämpfe fernhalten.
- Steckverbindungen im Außenbereich mit selbstverschweißendem Band abdichten.
- Blitzschutz und Erdung der Antennenanlage nach geltenden Vorschriften prüfen.

## NAS

Synology mit x86_64-CPU (2 Kerne) und 16 GB RAM, SSD- und HDD-Volume, Container Manager. Ausreichend für alle zentralen Dienste; der begrenzende Faktor ist die CPU.
