#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/services/api"
# Development code reload keeps the independently launched GPU worker alive.
# Explicit environment configuration still wins; make stop signals both.
for argument in "$@"; do
  if [[ "$argument" == "--reload" ]]; then
    export WORKER_SHUTDOWN_ON_API_EXIT="${WORKER_SHUTDOWN_ON_API_EXIT:-false}"
  fi
done
exec "$ROOT/.venv-api/bin/python" -m uvicorn app.main:app \
  --host "${BACKEND_HOST:-127.0.0.1}" --port "${BACKEND_PORT:-8000}" "$@"
