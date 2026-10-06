#!/usr/bin/env bash
# One command: start the Firebase Emulator Suite (demo project only), run every backend test
# against it, enforce coverage targets, run the Firestore/Storage security-rule tests, stop emulators.
#
#   ./scripts/test.sh                # everything
#   ./scripts/test.sh tests/unit -k scheduler   # extra args go to pytest
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="demo-athlethium"   # demo-* projects can never reach production
VENV="functions/venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3.12 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -r requirements-dev.txt
[ -d node_modules ] || npm ci --no-fund --no-audit

PYTEST_ARGS="${*:-}"
export REQUIRE_EMULATORS=1

npx firebase emulators:exec \
  --project "$PROJECT" \
  --only auth,firestore,functions,storage \
  "bash scripts/run_suites.sh $PYTEST_ARGS"
