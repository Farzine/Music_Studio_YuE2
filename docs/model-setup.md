# Models

## What gets downloaded

| Repository | Role | Size |
|---|---|---|
| `m-a-p/YuE2-3B` | Generation: plan, acoustic tokens, latent synthesis | 7.26 GB |
| `m-a-p/YuE2-Vae` | Listening decoder — the default | 507 MB |
| `m-a-p/YuE2-Vae-legacy` | Benchmark decoder, optional | ~500 MB |
| `m-a-p/SheetSage2` | Audio→ABC for covers, optional | see [cover-workflow.md](cover-workflow.md) |

```bash
./scripts/download_models.sh
```

The script requests only the files the runtime's own resolver allows —
`config.json`, `generation_config.json`, `yue2_generation_config.json`,
`weights_manifest.json`, `model.safetensors`, `qwen.tiktoken`, the modeling
module, the licence and the third-party notices. Example audio and packaged
wheels are not downloaded.

To put weights elsewhere:

```bash
YUE2_MODELS_DIR=/srv/models ./scripts/download_models.sh
# then point .env at them
YUE2_MODEL_PATH=/srv/models/YuE2-3B
YUE2_VAE_PATH=/srv/models/YuE2-Vae
```

If `YUE2_MODEL_PATH` does not exist, the studio falls back to the Hugging Face
repository id, which only works with `YUE2_LOCAL_FILES_ONLY=false`.

### The legacy decoder

```bash
uv tool run --from huggingface_hub hf download m-a-p/YuE2-Vae-legacy \
  --local-dir models/YuE2-Vae-legacy \
  --include config.json weights_manifest.json model.safetensors modeling_vae.py LICENSE
```

It appears in Advanced → Model → Decoder weights as soon as the directory
exists. Until then the option is disabled and says why. Use it to reproduce the
published benchmark protocol, not for listening.

## Verification

The pipeline hashes every weight file on load and records the result in each
manifest:

```jsonc
"weights": {
  "mot": { "files": { "model.safetensors": { "sha256": "1d55c42c…", "bytes": 7261441640 } },
           "config_sha256": "ad3477bb…" },
  "vae": { "files": { "model.safetensors": { "sha256": "…" } }, "config_sha256": "…" }
}
```

Two generations with the same weight hashes, the same effective configuration
and the same seed describe the same run. Compare `manifest_identity` to check at
a glance.

## Revisions

`model.revision` and `model.vae_revision` pin a Hugging Face revision, which
matters when you are comparing runs over time. They have no effect on a local
directory — there the file hashes are the identity.

## Keeping the model loaded

`MODEL_IDLE_UNLOAD_SECONDS=0` (the default) keeps the checkpoint resident
between jobs; reloading 7.26 GB per request would dominate a short generation.
The manager rebuilds the pipeline only when a job changes the model, decoder,
compute backend, quantization, AR offload, memory budget, offline flag, decoder
tile size or solver step count. Set a non-zero timeout if you need the GPU back
when the studio is idle.

## Precision

The unquantized bf16 preset is the quality default and fits comfortably in
48 GB — a 30-second generation peaks around 7.2 GiB. FP8 is offered only on
GPUs with compute capability 8.9 or newer; on an A6000 (sm_86) the option is
disabled and the System page says so.
