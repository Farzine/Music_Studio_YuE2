# Models

## Download from the studio

Open **Settings → Music models**, enter a Hugging Face repository ID such as
`audio-cpp/Yue2-3B-GGUF`, and browse its model files. You can also enter a
filename and branch or commit directly. The studio downloads the chosen file
plus the YuE2 files it needs, then offers **Use for a song**. Arbitrary files
can be downloaded, but only complete YuE2 safetensors checkpoints and supported
YuE2 GGUF packages are enabled for inference.

For GGUF inference on NVIDIA CUDA, build the optional audio.cpp CLI:

```bash
make install-audiocpp
```

The build is pinned to audio.cpp `v0.8.2` and needs CMake, a C++ compiler, and
the CUDA toolkit. If you already have a compatible CLI, set
`AUDIOCPP_CLI_PATH=/absolute/path/to/audiocpp_cli` in `.env` and restart the
worker. A GGUF job runs the CLI on the GPU selected on the System page. The
process exits after the job, releasing its GPU allocation. The native PyTorch
model remains available for other jobs and is unloaded before a GGUF job.

The System page estimates model capacity and assesses actual installed/inspected
metadata against free VRAM, VAE/cache/runtime overhead and configured reserves.
Unknown parameters stay Unknown; file size alone does not prove a model can run.
See [model recommendations](model-recommendations.md) for assumptions and limits.

## Downloaded and available are different states

Settings reports downloaded weights separately from inference availability. A
complete GGUF download remains **Downloaded** when audio.cpp is unavailable;
the UI shows the missing executable and how to install it. Missing sidecars,
unsupported GGUF packages and unreadable installation metadata have their own
reasons. Downloading does not select a model for a task or load it onto a GPU.

The API inventory exposes:

| Field | Meaning |
|---|---|
| `download_status` | Main weights exist (`downloaded`), are missing, or cannot be identified (`unknown`). |
| `files_complete` | The existing adapter's required files are present. |
| `validation_status` | `not_validated`, `validated` after structural checks, or `failed` with a specific corruption/metadata reason. |
| `registration_status` | `registered` for durable local records; `discovered` for unresolved repository defaults. Registration does not imply validation or loading. |
| `compatibility_status` | Current adapter file rules say supported/incompatible, or metadata cannot be interpreted. |
| `inference_status`, `inference_ready` | Preflight availability and its specific blocker, including a missing audio.cpp executable. |
| `currently_loaded` | Currently `null`: inventory scanning cannot establish worker/GPU residency. |
| `deletion_status` | `active`, or `deleting` while an interrupted cleanup needs retry. |

Preflight availability is not a successful load, checksum validation or a GPU
memory guarantee. Unknown parameter counts, precision and quantization remain
`null`, rather than being inferred from a repository name. The legacy `present`
field remains a projection of `inference_ready` for older clients.

The generation selector uses backend availability rules, and submission refuses
an unavailable model. The `default` choice resolves to the same configured
checkpoint in the API and worker, including GGUF installations. Model and VAE
remain separate stored fields; the current GGUF adapter still requires its
bundled F16 VAE.

## Local model registry

The first inventory scan imports configured native model/VAE directories and
recognized sibling or `models/hub` installations into
`DATA_DIR/model-registry.json`. Successful studio downloads register there
before their download job completes. Existing weights are neither moved nor
downloaded again. Repeated scans preserve IDs and timestamps, and do not
rewrite unchanged records. Concurrent imports use the existing filesystem lock
and atomic JSON write pattern.

Inventory `id` values remain existing directory paths so saved projects,
generation requests and default/standard/legacy choices keep working. Each
local installation also receives a deterministic `registry_id` based on its
canonical directory and role. Symlink path aliases share a record. Registry IDs
identify inspect/validate/delete API resources; task configuration still uses
paths or its existing sentinel choices. Moving a directory creates a new
installation ID.

Records retain source, repository, revision, filename, format, backend, known
file size and nullable metadata. `commit_hash` is populated only when the stored
revision is a full 40-character hexadecimal commit. `created_at` is the first
registration/import time, not a claim about when legacy weights were downloaded;
`updated_at` changes with installation metadata. Missing installations retain
their identity and last known facts, including size, while live download and
inference states report missing files. GPU residency and runtime readiness are
not persisted by this registry. File validation reports are stored separately
and applied only while their fingerprints match.

If the registry is damaged or has an unsupported schema version, the API reports
an actionable error and leaves the file untouched. Restore a valid backup. If
none is available, retain the damaged file under another name and request the
model inventory again to rebuild recognized local records. Deterministic IDs
are recovered from the same paths, but first-import dates, aliases no longer
discoverable, and registrations outside the scan roots require the backup.

## Structural validation and checksums

Use `POST /api/v1/models/{registry_id}/validate` with
`{"verify_checksum": false}` for structural checks, or `true` to also compute
weight SHA-256 hashes and compare available `weights_manifest.json` expectations.
These actions currently use the API; dedicated model action buttons are planned.
The API never imports PyTorch or loads tensors.

The readers follow the [safetensors format](https://github.com/huggingface/safetensors#format)
and [GGUF specification](https://github.com/ggml-org/ggml/blob/master/docs/gguf.md).
They check bounded headers, duplicate keys, tensor shapes and byte ranges,
truncation, overlaps and applicable alignment. The GGUF reader supports
little-endian v2/v3 and F32/F16/BF16, Q4_0/Q4_1, Q5_0/Q5_1 and Q8_0/Q8_1
tensor blocks. Other versions/encodings report **Needs validation**, not success.
Native inference still expects `model.safetensors` in the installation root;
other native layouts/shards need adapter integration in a later phase.

Compatibility compares declared model/VAE architecture and required files.
The audio.cpp package uses `general.architecture=audiocpp` plus
`audiocpp.model_spec.family=yue2` in the main file; it is supported alongside
YuE2 architecture metadata. Sidecar configs must declare YuE2 and its VAE, and
the current bundled GGUF VAE must store F16 tensors. A different filename alone
does not make a GGUF package incompatible. Native task admission checks the VAE
independently and rejects mismatched declared latent widths.

Reports live under `DATA_DIR/model-validations`. Inventory reuses a report only
while file device/inode, size, modification/change times and the required-file
list match. Changed complete installations require revalidation; corrupt or
failed reports block task admission. Metadata now includes observed precision,
quantization and `tensor_element_count`. Stored tensor elements include buffers
or duplicated weights and are **not** presented as an exact parameter count.
`parameter_count` remains unknown unless explicitly declared by model metadata.

Computed hashes without expected hashes are recorded but do not set
`checksum_verified=true`. Structural success does not verify weight values,
guarantee runtime loading or establish VRAM capacity. Full hash verification
can take time for large files; it runs only when requested. File fingerprints
detect ordinary edits; they are not continuous cryptographic verification.

## Confirmed model deletion

Inspect `GET /api/v1/models/{registry_id}/deletion-preview` before deleting. It
returns the exact directory/file list, estimated allocated disk space reclaimed,
blockers and a confirmation token. `DELETE /api/v1/models/{registry_id}` requires
both that token and `confirmed_path`. Changed files or paths require a new
preview and confirmation. Dedicated UI confirmation is planned with the Models
page; there is no automatic deletion on download or selection.

Deletion refuses unfinished task references (including queued/cancel-requested
work), in-use model/VAE files, overlapping registered installations, mounted
files/directories and protected application data/config/runtime directories.
Only installations within `YUE2_MODELS_DIR` can be deleted through this API;
external installations require manual removal. Unreadable task/worker records
block deletion rather than being silently skipped. Workers predating file
leases must be stopped/unloaded when their heartbeat reports the model resident.

New workers hold shared file leases for each job and for the lifetime of native
model/VAE residency. Downloads hold an exclusive lease on their destination;
validation uses a shared lease. Deletion requests fail promptly on lease
conflicts, and coordinate with task admission through the existing queue lock.
These advisory locks coordinate studio processes, not arbitrary external file
edits.

Confirmed deletion records a journal in the registry, renames the installation
to a hidden sibling on the same filesystem and removes that directory. Partial
and incomplete downloads inside it are included. Symlink targets and other hard
links are preserved. Registry removal follows successful cleanup; failed or
interrupted cleanup stays visible as `deleting` and cannot be used for inference.
Inspect a fresh preview and retry to finish cleanup. Do not discard a registry
backup while it contains deletion journals. Filesystem power-loss durability is
subject to the existing Store/OS guarantees; this is not a transactional database.

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

The native worker accepts explicit Load and Unload through the
[runtime API](api.md#model-runtime-commands). Requests are queued; wait for worker
acknowledgement rather than treating HTTP acceptance as loading. The System page
shows lifecycle, model/VAE placement, active CLI process and cleanup failures.
Dedicated Installed Models action buttons follow in the UX phase.

Load supports native torch/torch-eager and materializes the model weights; the
VAE is retained lazily and is loaded during decoding. The runtime can move models
and VAEs back to CPU, so retained weights do not imply current GPU residency.
The pinned vLLM backend starts its child during generation and has no preload
interface. The audio.cpp CLI likewise loads GGUF per generation; neither receives
a fake successful persistent Load acknowledgement.

Commands wait for active inference and run before new queued generations. A model
and its VAE cannot be deleted while a pending command or resident file lease needs
them. Restarting a worker fails an interrupted old command without replay. If the
worker is offline, restart it and inspect the latest runtime state before submitting
again. A successful command result describes that moment, not future residency.

Unload releases the complete managed pipeline and resources. If close/cache cleanup
fails, `MODEL_UNLOAD_FAILED` and UNLOAD_FAILED remain visible, and new loads are
blocked until explicit Unload succeeds. CUDA contexts and other processes' memory
are not model residency. GPU switching now waits for active inference, checks
native references/child exit and worker CUDA allocator cleanup, then prepares the
previous model on the target before committing the device. Target failure attempts
rollback; uncertain cleanup blocks another allocation. See [Choosing a GPU](api.md#choosing-a-gpu)
for queued stages, errors and deferred vLLM/audio.cpp loading. Physical GPU smoke
verification remains pending. Graceful worker/API shutdown now settles active
operations, attempts model/VAE/child cleanup and records acknowledgement/errors;
see [Shutdown](api.md#shutdown) for coupling, deadlines and interrupted-job recovery.
Hard OS termination cannot guarantee Python cleanup.

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
