#!/bin/bash
# Simulierte Empfangsstation: Datenverzeichnis und SSH-Zugang wie auf dem echten Pi.
set -euo pipefail

mkdir -p /data/current /data/complete /data/acked
chown -R 1000:1000 /data
chmod 2775 /data /data/current /data/complete /data/acked

if [[ ! -f /keys/ingest_read ]]; then
  ssh-keygen -q -t ed25519 -N "" -C ingest-read -f /keys/ingest_read
  ssh-keygen -q -t ed25519 -N "" -C ingest-ack -f /keys/ingest_ack
fi
chown 1000:1000 /keys/ingest_read /keys/ingest_ack
chmod 600 /keys/ingest_read /keys/ingest_ack

install -d -m 700 -o flightdb-sync -g flightdb /home/flightdb-sync/.ssh
{
  echo "command=\"rrsync -ro /data/complete\",restrict $(cat /keys/ingest_read.pub)"
  echo "command=\"rrsync -wo /data/acked\",restrict $(cat /keys/ingest_ack.pub)"
} > /home/flightdb-sync/.ssh/authorized_keys
chown flightdb-sync:flightdb /home/flightdb-sync/.ssh/authorized_keys
chmod 600 /home/flightdb-sync/.ssh/authorized_keys

ssh-keygen -A
exec /usr/sbin/sshd -D -e
