#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/services/api"
exec "$ROOT/.venv-api/bin/python" -m uvicorn app.main:app \
  --host "${BACKEND_HOST:-127.0.0.1}" --port "${BACKEND_PORT:-8000}" "$@"
