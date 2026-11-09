#!/usr/bin/env bash
# pre-commit: verhindert sensible Inhalte im öffentlichen Repo.
# Muster stehen lokal in config/local/sensitive-patterns.txt (gitignored), eine Regex pro Zeile.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
patterns="$root/config/local/sensitive-patterns.txt"
fail=0

email=$(git config user.email || true)
if [[ "$email" != *@users.noreply.github.com ]]; then
  echo "FEHLER: git user.email ist keine noreply-Adresse." >&2
  fail=1
fi

if [[ ! -s "$patterns" ]]; then
  echo "FEHLER: $patterns fehlt oder ist leer." >&2
  exit 1
fi

if git diff --cached -U0 --no-color | grep '^+' | grep -v '^+++' | grep -inEf "$patterns"; then
  echo "FEHLER: sensible Inhalte im Commit (siehe oben)." >&2
  fail=1
fi

if git diff --cached --name-only | grep -iEf "$patterns"; then
  echo "FEHLER: sensibler Dateiname im Commit." >&2
  fail=1
fi

exit $fail
