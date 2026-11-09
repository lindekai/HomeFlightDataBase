#!/bin/bash
# Nächtlicher pg_dump (Custom-Format) nach /dumps; behält die letzten BACKUP_KEEP Dumps.
# Aufruf mit --once für einen sofortigen Dump (Test/Restore-Probe).
set -euo pipefail

keep="${BACKUP_KEEP:-14}"
hour="${BACKUP_HOUR:-3}"

dump() {
  local f="/dumps/flightdb_$(date -u +%Y%m%dT%H%M%SZ).dump"
  pg_dump -Fc -f "$f.tmp"
  mv "$f.tmp" "$f"
  ls -1t /dumps/flightdb_*.dump | tail -n +"$((keep + 1))" | xargs -r rm --
  echo "{\"level\":\"info\",\"msg\":\"Backup erstellt\",\"file\":\"$f\"}"
}

if [[ "${1:-}" == "--once" ]]; then
  dump
  exit 0
fi

while true; do
  now=$(date +%s)
  next=$(date -d "today ${hour}:00" +%s)
  (( next <= now )) && next=$(date -d "tomorrow ${hour}:00" +%s)
  sleep $(( next - now ))
  dump || echo '{"level":"error","msg":"Backup fehlgeschlagen"}' >&2
done
