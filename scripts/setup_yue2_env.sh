#!/usr/bin/env bash
# Build the dedicated YuE2 inference environment (.venv-yue2).
#
# Torch is installed from the cu126 index to match the installed NVIDIA driver
# (560.x / CUDA 12.6) instead of the cu128 build that PyPI's default torch
# 2.10.0 wheel bundles. yue2-infer pins `torch==2.10.0`, which a local version
# such as 2.10.0+cu126 satisfies.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${YUE2_VENV:-$ROOT/.venv-yue2}"
TORCH_INDEX="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu126}"
YUE2_REF="${YUE2_REF:-git+https://github.com/multimodal-art-projection/YuE.git}"

uv venv --python 3.12 --allow-existing "$VENV"
export VIRTUAL_ENV="$VENV"

# pypi.nvidia.com (mirrored by the PyTorch index) intermittently times out on
# the large CUDA wheels; retry instead of leaving a half-built environment.
retry() {
  local attempts=${RETRY_ATTEMPTS:-6} n=1
  until "$@"; do
    if [ "$n" -ge "$attempts" ]; then
      echo "[setup] giving up after $n attempts: $*" >&2
      return 1
    fi
    echo "[setup] attempt $n failed, retrying in 10s: $*" >&2
    n=$((n + 1))
    sleep 10
  done
}

echo "[setup] torch 2.10.0 (cu126)"
retry uv pip install --python "$VENV/bin/python" "torch==2.10.0" --index-url "$TORCH_INDEX"

echo "[setup] yue2-infer runtime dependencies"
retry uv pip install --python "$VENV/bin/python" \
  "transformers==4.57.6" "huggingface-hub==0.36.2" "safetensors==0.7.0" \
  "tiktoken==0.12.0" "numpy==2.2.6" "soundfile==0.13.1" "accelerate==1.13.0"

echo "[setup] yue2-infer (no deps: torch variant is already pinned above)"
retry uv pip install --python "$VENV/bin/python" --no-deps "$YUE2_REF"

echo "[setup] worker support packages"
retry uv pip install --python "$VENV/bin/python" "pydantic>=2.9,<3" "nvidia-ml-py>=12.560"

"$VENV/bin/python" - <<'PY'
import torch, yue2
print("[setup] torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
print("[setup] yue2", yue2.__version__)
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print("[setup] gpu", p.name, round(p.total_memory / 2**30, 1), "GiB", f"sm_{p.major}{p.minor}")
    print("[setup] bf16", torch.cuda.is_bf16_supported())
PY
echo "[setup] done -> $VENV"
