# Deployment der Empfangsstation (Raspberry Pi)

## 1. Betriebssystem

- Raspberry Pi Imager: *Raspberry Pi OS Lite (64-bit)*, SSH mit Schlüssel, WLAN, Hostname setzen.
- Pufferspeicher bevorzugt auf USB-SSD, eingehängt unter `/srv/flightdb`.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y chrony rsync git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

## 2. DVB-Treiber sperren

Der Kernel-Treiber für DVB-T-Sticks blockiert das SDR für readsb:

```bash
printf 'blacklist dvb_usb_rtl28xxu\nblacklist rtl2832\nblacklist rtl2830\n' | \
  sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf
sudo reboot
```

## 3. Benutzer, Gruppe und Datenverzeichnis

```bash
sudo groupadd -g 1000 flightdb 2>/dev/null || true   # GID muss RECORDER_GID entsprechen
sudo useradd -m -g flightdb -s /bin/sh flightdb-sync
sudo usermod -p '*' flightdb-sync                    # kein Passwort, nur Schlüssel
sudo mkdir -p /srv/flightdb/data/{current,complete,acked}
sudo chown -R 1000:flightdb /srv/flightdb/data
sudo chmod 2775 /srv/flightdb/data /srv/flightdb/data/{current,complete,acked}
```

Hinweis: Hat der Standardbenutzer des Pi bereits UID/GID 1000, `RECORDER_UID`/`RECORDER_GID`
in `.env` auf diese Werte setzen und `flightdb-sync` zusätzlich in diese Gruppe aufnehmen.

## 4. Zugang für das NAS

`/home/flightdb-sync/.ssh/authorized_keys` (Inhalt der beiden `.pub`-Dateien vom NAS):

```text
command="rrsync -ro /srv/flightdb/data/complete",restrict ssh-ed25519 AAAA… ingest-read
command="rrsync -wo /srv/flightdb/data/acked",restrict ssh-ed25519 AAAA… ingest-ack
```

```bash
sudo chown -R flightdb-sync:flightdb /home/flightdb-sync/.ssh
sudo chmod 700 /home/flightdb-sync/.ssh && sudo chmod 600 /home/flightdb-sync/.ssh/authorized_keys
which rrsync   # erwartet /usr/bin/rrsync
```

Test vom NAS: `ssh -i ingest_read flightdb-sync@<pi>` muss abgelehnt werden (keine Shell);
`rsync -e "ssh -i ingest_read" flightdb-sync@<pi>: /tmp/x/` muss funktionieren.

## 5. SDR prüfen und Stack starten

```bash
lsusb                                  # RTL2832U: 0bda:2838 oder 0bda:2832
git clone <repo-url> ~/flightdb && cd ~/flightdb/receiver
cp .env.example .env && chmod 600 .env  # Standort, SDR-Seriennummer, IDs eintragen
docker compose up -d --build
docker compose ps
```

Live-Karte im LAN: `http://<pi>:8080`.

## 6. Einspeisung

Nach Registrierung bei den Netzwerken (Schlüssel in `.env`):

```bash
docker compose --profile feeders up -d
```

- FlightAware: Standort für MLAT auf der Seite „My ADS-B“ hinterlegen.
- OpenSky: Seriennummer nach dem ersten Start aus dem Log in `OPENSKY_SERIAL` übernehmen.
- Wo angeboten, öffentliche Standortanzeige auf „ungenau“ stellen.

## 7. Prüfen

```bash
docker compose logs -f recorder
ls -R /srv/flightdb/data/complete | tail
```
