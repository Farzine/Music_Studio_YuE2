# Setup on Linux with an NVIDIA GPU

Verified on Ubuntu 22.04, NVIDIA RTX A6000 (48 GB), driver 560.28.03.

## Requirements

| | |
|---|---|
| GPU | BF16-capable NVIDIA, 24 GB minimum, 48 GB comfortable |
| Driver | 525 or newer. `nvidia-smi` must work. |
| Python | 3.12 for the worker, 3.11 for the API. `uv` installs 3.12 if it is missing. |
| Node | 20 or newer (tested on 22) |
| Disk | ~8 GB for weights, plus room for audio |
| FFmpeg | Optional; only for MP3 delivery. 6.1+ is additionally required for the cover workflow. |

Check the GPU first:

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
```

Install `uv` if you do not have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 1. Environments

```bash
./scripts/setup_api_env.sh      # .venv-api   — FastAPI, deliberately no torch
./scripts/setup_yue2_env.sh     # .venv-yue2  — torch 2.10.0+cu126 + yue2-infer
cd apps/web && npm install && cd ../..
```

Or `make install`.

**Why cu126 and not the default wheel.** `yue2-infer` pins `torch==2.10.0`,
whose PyPI wheel bundles CUDA 12.8. Driver 560 is a CUDA 12.6 driver, so the
setup script installs torch from `https://download.pytorch.org/whl/cu126`
instead. The pin `torch==2.10.0` is satisfied by the local version
`2.10.0+cu126`. Override with `TORCH_INDEX_URL` if your driver differs.

The script retries the large CUDA wheels; `pypi.nvidia.com` intermittently times
out on them, and a half-built environment is worse than a slow one.

Confirm:

```bash
.venv-yue2/bin/python -c "import torch, yue2; \
print(torch.__version__, torch.cuda.is_available(), torch.cuda.is_bf16_supported(), yue2.__version__)"
# 2.10.0+cu126 True True 0.1.6
```

## 2. Weights

```bash
./scripts/download_models.sh    # or: make models
```

Downloads `m-a-p/YuE2-3B` (7.26 GB) and `m-a-p/YuE2-Vae` (507 MB) into `./models`,
restricted to the same public file list the runtime itself resolves — no
example audio, no wheels. See [model-setup.md](model-setup.md).

## 3. Configuration

```bash
cp .env.example .env
```

The values worth knowing:

```env
YUE2_MODEL_PATH=./models/YuE2-3B
YUE2_VAE_PATH=./models/YuE2-Vae
DATA_DIR=./data

CUDA_VISIBLE_DEVICES=0          # which GPU the worker uses
MAX_CONCURRENT_GPU_JOBS=1       # raise only with more GPUs
YUE2_MEMORY_BUDGET_GIB=40       # 24 is the documented baseline; 40 suits a 48 GB card
YUE2_BACKEND=native             # native | mock | comfy
MODEL_IDLE_UNLOAD_SECONDS=0     # 0 keeps the 7.26 GB checkpoint resident
```

Nothing is hard-coded: both processes read this file at startup. Restart them
after changing it.

## 4. Prove the GPU path works

```bash
make smoke-test
# or: .venv-yue2/bin/python scripts/smoke_test.py --seconds 30
```

This queues one real generation, runs the worker against it in-process, and
prints per-stage timings, peak VRAM and the audio file it wrote. Expect roughly:

```json
{ "status": "COMPLETED", "elapsed_seconds": 28.6,
  "timing": { "model_load_seconds": 4.15, "planning_seconds": 10.86,
              "semantic_seconds": 6.9, "synthesis_seconds": 2.71,
              "decode_seconds": 3.0 },
  "gpu_peak_gib": 7.24 }
```

If this fails, the web application will fail the same way. Fix it here first.

## 5. Run

```bash
make dev
```

or three terminals:

```bash
./scripts/dev_api.sh --reload         # http://127.0.0.1:8000  (docs at /docs)
./scripts/dev_worker.sh
npm --prefix apps/web run dev         # http://127.0.0.1:3000
```

The frontend proxies `/api/v1` and `/ws` to the API, so the browser stays on one
origin and audio range requests and SSE behave normally.

Check <http://127.0.0.1:3000/system>: the GPU, the worker state, the runtime
versions and the capability list should all be populated.

## 6. Tests

```bash
make test           # 69 tests, no GPU needed — uses the mock backend
make typecheck      # TypeScript
```

The suite splits across both environments: 60 tests run in `.venv-api`
(domain, API, mock worker) and 9 more in `.venv-yue2` (model residency,
which needs `yue2` importable but never touches the GPU). `make test` runs
both.

## Running without a GPU

Set `YUE2_BACKEND=mock`. Every screen, the queue, cancellation, artifacts,
manifests and the score editor work; the audio is a generated tone and is
labelled as such in the manifest and the capability document.

## Notes on exposure

The API binds to `127.0.0.1` by default. There is no authentication, because
there are no accounts. Do not bind it to `0.0.0.0` on a shared network without
putting authentication in front of it first.
