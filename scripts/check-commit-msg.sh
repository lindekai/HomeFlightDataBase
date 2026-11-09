#!/usr/bin/env bash
# commit-msg: keine Attribution an KI-Werkzeuge in Commit-Nachrichten.
set -euo pipefail

if grep -qiE '^co-authored-by:.*(claude|anthropic)|generated with .*claude' "$1"; then
  echo "FEHLER: Commit-Nachricht enthält eine Claude-Attribution." >&2
  exit 1
fi
