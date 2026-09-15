#!/usr/bin/env bash
# Download YuE2 weights into ./models using the same file boundary as
# yue2.storage.resolve_model (explicit public model files only).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${YUE2_MODELS_DIR:-$ROOT/models}"
HF="uv tool run --from huggingface_hub[cli] hf"

MODEL_FILES=(config.json generation_config.json yue2_generation_config.json
             weights_manifest.json model.safetensors qwen.tiktoken
             modeling_yue2.py LICENSE THIRD_PARTY_NOTICES.md 'licenses/*')
VAE_FILES=(config.json weights_manifest.json model.safetensors modeling_vae.py
           LICENSE THIRD_PARTY_NOTICES.md 'licenses/*')

include_args() { for f in "$@"; do printf -- '--include\n%s\n' "$f"; done; }

echo "[download] m-a-p/YuE2-3B -> $MODELS_DIR/YuE2-3B"
mapfile -t args < <(include_args "${MODEL_FILES[@]}")
$HF download m-a-p/YuE2-3B --local-dir "$MODELS_DIR/YuE2-3B" "${args[@]}"

echo "[download] m-a-p/YuE2-Vae -> $MODELS_DIR/YuE2-Vae"
mapfile -t args < <(include_args "${VAE_FILES[@]}")
$HF download m-a-p/YuE2-Vae --local-dir "$MODELS_DIR/YuE2-Vae" "${args[@]}"

echo "[download] done"
du -sh "$MODELS_DIR"/* || true
