#!/usr/bin/env bash
set -euo pipefail
PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" -m app.cli seed-demo
"$PYTHON" -m app.cli export-demo
export DEMO_MODE=true
export DATABASE_URL="${DATABASE_URL:-out/demo/sim.db}"
exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
