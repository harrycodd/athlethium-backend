#!/usr/bin/env bash
# Executed *inside* `firebase emulators:exec` (emulator env vars are already set).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="functions/venv/bin/python"

if [ "$#" -gt 0 ]; then
  exec "$PY" -m pytest "$@"
fi

# 1) Full backend suite with coverage, >= 80% overall.
"$PY" -m pytest --cov --cov-report=term-missing --cov-report=xml --cov-fail-under=80

# 2) Plan-generation logic must be 100% covered (line + branch).
"$PY" -m coverage report --fail-under=100 \
  --include='functions/engine/*,functions/generators/*'

# 3) Firestore + Storage security rules.
npm run --silent test:rules
