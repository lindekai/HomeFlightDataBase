#!/usr/bin/env bash
# Verlinkt die Schutz-Hooks in .git/hooks.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
ln -sf ../../scripts/check-sensitive.sh "$root/.git/hooks/pre-commit"
ln -sf ../../scripts/check-commit-msg.sh "$root/.git/hooks/commit-msg"
chmod +x "$root/scripts/"*.sh
echo "Hooks installiert."
