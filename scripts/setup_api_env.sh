#!/usr/bin/env bash
# Build the API environment (.venv-api). Deliberately free of torch: the API
# process never imports the model runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${API_VENV:-$ROOT/.venv-api}"

uv venv --python 3.11 --allow-existing "$VENV"
uv pip install --python "$VENV/bin/python" -r "$ROOT/services/api/requirements.txt"
uv pip install --python "$VENV/bin/python" -e "$ROOT/packages/core"
echo "[setup] done -> $VENV"
