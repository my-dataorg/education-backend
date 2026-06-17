#!/usr/bin/env bash
# Start education-backend (port 8010)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8010}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  echo "Created Python virtualenv (.venv)"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

echo "Starting education-backend on http://localhost:${PORT}"
echo "Requires: Postgres, Keycloak, platform-backend (8002)"
exec uvicorn app.main:app --reload --host 0.0.0.0 --port "$PORT"
