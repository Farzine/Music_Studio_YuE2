#!/usr/bin/env bash
# Install everything the cover workflow needs:
#   1. a static FFmpeg 6.1+ (SheetSage2 requires it; Ubuntu 22.04 ships 4.4.2)
#   2. the m-a-p/SheetSage2 weights
#   3. .venv-sheetsage2 — a separate environment, because SheetSage2 pins
#      torch 2.8.0 / transformers 4.45.2 against YuE2's 2.10.0 / 4.57.6
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${YUE2_MODELS_DIR:-$ROOT/models}"
VENV="${SHEETSAGE2_VENV:-$ROOT/.venv-sheetsage2}"
TOOLS="$ROOT/tools"
FFMPEG_URL="${FFMPEG_URL:-https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz}"

echo "[cover] 1/4 static ffmpeg"
if [ -x "$TOOLS/ffmpeg/ffmpeg" ] && "$TOOLS/ffmpeg/ffmpeg" -version >/dev/null 2>&1; then
  echo "[cover] already present: $("$TOOLS/ffmpeg/ffmpeg" -version | head -1)"
else
  mkdir -p "$TOOLS/ffmpeg"
  tmp="$(mktemp -d)"
  curl -fL --retry 5 --retry-delay 5 -o "$tmp/ffmpeg.tar.xz" "$FFMPEG_URL"
  tar -xJf "$tmp/ffmpeg.tar.xz" -C "$tmp"
  build="$(find "$tmp" -maxdepth 1 -type d -name 'ffmpeg-*' | head -1)"
  install -m 0755 "$build/ffmpeg" "$build/ffprobe" "$TOOLS/ffmpeg/"
  rm -rf "$tmp"
  echo "[cover] installed: $("$TOOLS/ffmpeg/ffmpeg" -version | head -1)"
fi

echo "[cover] 2/4 SheetSage2 weights"
# Transcription needs the model and its code, not the notation-rendering
# assets. Each pattern needs its own --exclude; extra bare arguments would be
# read as explicit filenames to fetch instead.
uv tool run --from huggingface_hub hf download m-a-p/SheetSage2 \
  --local-dir "$MODELS_DIR/SheetSage2" \
  --exclude 'render_assets/*' --exclude 'benchmarks/*' --exclude 'assets/*'

# SheetSage2's configuration selects the MERT-v2-FullSong encoder by repo id,
# so it has to be in the Hugging Face cache for offline transcription to work.
echo "[cover] 3/4 MERT-v2-FullSong encoder"
uv tool run --from huggingface_hub hf download m-a-p/MERT-v2-FullSong

echo "[cover] 4/4 environment"
uv venv --python 3.11 --allow-existing "$VENV"
retry() {
  local attempts=${RETRY_ATTEMPTS:-5} n=1
  until "$@"; do
    [ "$n" -ge "$attempts" ] && { echo "[cover] giving up: $*" >&2; return 1; }
    echo "[cover] attempt $n failed, retrying in 10s" >&2; n=$((n + 1)); sleep 10
  done
}
retry uv pip install --python "$VENV/bin/python" \
  torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu126
retry uv pip install --python "$VENV/bin/python" -r "$MODELS_DIR/SheetSage2/requirements.txt"

"$VENV/bin/python" - <<'PY'
import torch, transformers
print("[cover] torch", torch.__version__, "cuda", torch.cuda.is_available())
print("[cover] transformers", transformers.__version__)
PY
echo "[cover] done. Set SHEETSAGE2_MODEL_PATH and restart the API."
