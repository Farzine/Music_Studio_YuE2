# API

Base URL `http://127.0.0.1:8000`. Interactive documentation at `/docs`.

## Model setup

- `GET /api/v1/system/model-recommendation` assesses registered native/GGUF models for the selected GPU.
- `GET /api/v1/models/hub?repo_id=owner/name&revision=main` lists remote GGUF and safetensors files.
- `POST /api/v1/models/hub/inspect` accepts `repo_id`, optional `revision`/`device_index`; returns resolved commit, branches/tags, all file sizes/checksums, metadata and hardware assessments.
- `POST /api/v1/models/hub/preview` adds a primary `filename`, optional `mode` (`single`, `selected`, `repository`) and `selected_files`; reports selection, actual destination disk space and compatibility.
- `GET /api/v1/models/hub/discover?base_model=m-a-p/YuE2-3B&limit=10` inspects quantized-lineage repositories, including per-repository errors and hardware assessments. Optional `device_index`; limit 1–20.
- `POST /api/v1/models/downloads` accepts `{ "repo_id": "owner/name", "filename": "file.gguf", "revision": "main" }`, optional `mode` (default `single`) and `selected_files`. All three modes transfer content. It returns 202 with a queued job, immutable commit and exact file selection; invalid selections or insufficient known disk space fail before queuing.
- `GET /api/v1/models/downloads` and `GET /api/v1/models/downloads/{id}` report `queued`, `downloading`, `verifying`, `registering`, `complete` or `failed`. Jobs include `files`, `total_bytes`, `downloaded_bytes`, nullable `percentage`, `current_file`, `current_file_bytes`, nullable `current_file_total_bytes`/`current_file_percentage`, nullable `bytes_per_second`/`eta_seconds`, `attempt`, `error`, and allocated staging `partial_bytes`. Completed jobs also report `path`, `registry_id`, `validation_status` and `inference_status`. Legacy completed/failed records remain readable with their original fields.
- `POST /api/v1/models/downloads/{id}/retry` returns 202 and queues only a failed/interrupted job, retaining its pinned commit, selection and resumable staging. A legacy job resolves its original revision once when upgraded.
- `DELETE /api/v1/models/downloads/{id}/partial` removes only a failed job's private staging files, preserving the job and installed models. Active/complete jobs return 409. Only one active download is admitted across API processes.

Models → Download Model polls transfer status every two seconds. Repository
inspection and preview accept an explicitly evaluated `device_index` without
changing worker selection; the UI submits the immutable preview commit. Selection
changes invalidate the preview. Models → Recommended Models uses the existing
recommendation/discovery endpoints and backend ranking/reasons.

`complete` means content was downloaded and
registered, independently of inference readiness or GPU residency. Missing runtime
prerequisites and unsupported formats remain explicit inventory blockers. Repository
mode registers the chosen primary model; alternate weights are retained as content.
SDK progress measures logical file bytes, including resume/cache reuse, rather than
network-interface traffic. Unknown totals yield no fabricated percentage or ETA.

See [Hugging Face model management](huggingface-models.md) for metadata provenance,
selection modes, Unknown fields, authentication, errors and current transfer limits.

Every error uses the same envelope:

```json
{
  "error_code": "CUDA_OOM",
  "error_message": "CUDA out of memory …",
  "guidance": "The GPU ran out of memory at this stage. Your requested configuration was kept unchanged…",
  "stage": "decoding",
  "details": {}
}
```

Codes come from `ErrorCode`; see [troubleshooting.md](troubleshooting.md).

## System

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/health` | Liveness, and whether the model and worker are ready. |
| `GET` | `/api/v1/system/info` | Physical GPUs (NVML), CPU/RAM, disk, queue, worker heartbeat and runtime versions. |
| `GET` | `/api/v1/system/vram-estimate` | `?seconds=&decoder_mode=&budget_gib=` — returns a warning or `null`. An estimate, clearly labelled as one; it never changes the request. |
| `GET` | `/api/v1/system/gpus` | Worker CUDA GPUs with runtime/precision/residency facts; informational physical cards when offline. Check `selectable`. |
| `GET` | `/api/v1/system/runtime` | Worker heartbeats with lifecycle, model/VAE placement, command ID, session and online/stale status; configured `selected_device_index` is separate from actual residency. |
| `GET` | `/api/v1/system/model-recommendation` | Per-GPU capacity and explainable registered-model assessments. Optional device/VAE/offload/compute/budget scenario. |
| `PUT` | `/api/v1/system/device` | `{"device_index": 1}` — queue a coordinated GPU switch (202); an active run finishes on its captured device. |

### Model runtime commands

| Method | Path | Request/result |
|---|---|---|
| POST | `/api/v1/models/{registry_id}/load` | Optional `{ "config": { "model": { "vae": "standard", "compute_backend": "torch" } } }`; 202 with queued command. |
| POST | `/api/v1/models/{registry_id}/unload` | No body; 202 with queued command. |
| GET | `/api/v1/models/runtime-commands/{command_id}` | Persisted acknowledgement and matching-session `worker_online`. |

Load accepts the existing GenerationConfig schema; the route's registry model is
authoritative, and any `config.model.checkpoint` is replaced by its directory.
VAE paths/sentinels and VAE registry IDs are accepted independently. Other pipeline
settings, including decoder tiles and solver steps, retain their defaults unless
provided. Invalid roles/models fail admission. The updated native worker must be
online and expose a session ID; older, stopped, mock or remote Comfy workers cannot
receive these local residency commands.

Commands contain `id`, `worker_id`, `worker_session`, `operation`, `registry_id`,
`reference`, `config`, frozen `device_index`, timestamps, `status`, nullable `result`
and `error`. Status is `queued → running → succeeded/failed`. HTTP 202 confirms
queueing only. Poll for acknowledgement; `result` is a historical worker snapshot,
while `/system/runtime` is the latest heartbeat. Offline/expired snapshots never
prove current loading. One pending command is admitted per worker. Commands wait
for active inference and take precedence over new job claims. Pending model/VAE
references prevent deletion. A new worker session fails interrupted old commands
without replaying them; clients can inspect state and submit again.

The worker rechecks files and persisted validation fingerprints, declared VAE
compatibility, current GPU precision and the shared VRAM safety estimate before
allocation. Native torch/torch-eager Load explicitly materializes the lazy runtime's
model weights. The VAE remains lazy until decoding. GGUF audio.cpp and pinned vLLM
have no persistent preload interface: Load returns an explicit unsupported error;
their existing generation paths remain available.

Heartbeat `model` now includes `lifecycle`, `pipeline_ready`, `loaded`, `error`,
`model_device`, `vae_device`, nullable `model_gpu_resident`/`vae_gpu_resident`,
`residency_mode`, `residency_known` and `process_id`, alongside existing fields.
Lifecycle is UNLOADED, LOADING, LOADED, IN_USE, IDLE, UNLOADING, LOAD_FAILED or
UNLOAD_FAILED. Retained CPU weights differ from GPU residency. Native placement
uses tensor device metadata; per-job audio.cpp exposes its process and active
device with unknown tensor residency. `MODEL_UNLOAD_FAILED` means cleanup could
not be confirmed; retry Unload before loading another model or switching GPUs.
Worker shutdown reports a separate `WORKER_SHUTDOWN_FAILED` for cleanup/bookkeeping
errors; `model.lifecycle` still describes whether native release succeeded.

### Choosing a GPU

The device list comes from the worker, not from the API's own NVML query,
because `CUDA_VISIBLE_DEVICES` can hide cards from the worker that NVML still
sees — offering an index the worker cannot address would not be a real choice.
Worker logical indices are matched to NVML physical cards by UUID, including
hidden/reordered devices. No matching UUID means no live NVML merge; memory
then comes from the worker heartbeat. Names and indices never establish identity.
`cuda_visible_devices` reports the worker's actual environment, not API settings.
When the worker is offline, physical cards are informational (`selectable=false`,
`cuda_available=null`). Selecting a device requires a worker-confirmed CUDA index;
unavailable choices return 422. An online worker reporting no CUDA cards yields
an empty list even if NVML sees physical cards.

```jsonc
{
  "selected_index": 0,          // last worker-committed selection
  "active_index": 0,            // what the worker is using at this moment
  "pending_restart": false,     // legacy selected/active mismatch flag; no restart required
  "switch_command": {
    "id": "cmd_example", "device_index": 1, "status": "queued",
    "worker_online": true, "progress": null, "error": null
  },
  "devices": [
    { "index": 0, "name": "NVIDIA RTX A6000", "memory_free_bytes": 13207764992,
      "uuid": "GPU-example", "physical_index": 1, "selectable": true,
      "cuda_available": true, "cuda_runtime": "12.6", "memory_source": "nvml",
      "other_process_count": 1, "other_process_bytes": 37346082816, "selected": true }
  ]
}
```

PUT returns the existing GPU inventory shape plus `switch_command`. It does not
immediately change `selected_index`. Poll GET `/system/gpus` (latest switch) or
GET `/models/runtime-commands/{id}` (that request's outcome). Commands use the
same worker session and serial admission as Load/Unload; a second pending command
returns 409. Old workers without `select_device_commands` need an update/restart
before using this route; regular switches then require no restart.

Stages are `unloading`, `released`, `loading`, `ready`, or failure recovery
`rolling_back` / `restored`. The worker waits for active inference, releases old
references/children, synchronizes CUDA, clears caches and checks its own allocator
before target preparation. Selection is stored in `data/runtime-settings.json`
only after success. Target failure attempts previous model/device restoration;
error details include `rollback_succeeded` and `rollback_error`. Failed cleanup
blocks further loading so the worker never intentionally overlaps GPU residency.

An unloaded worker switches without loading an arbitrary default model. Native
torch weights reload on the target; VAE remains lazy. Pinned vLLM prepares its
wrapper and starts weights during generation; audio.cpp has no resident pipeline
and starts its next CLI job on the new device. Allocator verification covers worker
torch allocations, not other applications, driver contexts or a full NVML memory
census. Graceful/abnormal shutdown handling is a separate lifecycle concern.

### Shutdown

SIGINT/SIGTERM, worker task cancellation and normal API lifespan exit request
shutdown through the same session-bound command journal. Shutdown is a priority
request and can coexist with an already running Load/switch. Active native thread
operations settle before resources are released; generation cancellation uses
existing safe boundaries. Pending Load/Unload/switch requests fail with CANCELLED;
already acknowledged commands remain historical. Shutdown is acknowledged after
cleanup attempts, with the final model snapshot and any cleanup error.

Heartbeat fields add `accepting_work`, `shutdown.status` (`running`, `completed`,
`failed`) and `shutdown.errors` (`stage`, `message`), with `state=stopping` then
`stopped`. Stopping workers are not online/available for new runtime work; generation
admission returns 409 during a pending shutdown, before creating a project/job.
Waiting jobs are preserved. After the worker stops, offline generation queuing is
still supported for its next start. Startup under the exclusive process lease marks
abandoned active jobs failed/cancelled and does not replay them.

`WORKER_SHUTDOWN_ON_API_EXIT=true` (default) requests shutdown of the configured
worker; the API never imports CUDA models. `WORKER_SHUTDOWN_TIMEOUT_SECONDS=60`
bounds the API's acknowledgement wait. Expiry logs an unacknowledged request rather
than claiming GPU release. Old workers without shutdown-command support must be
stopped using their launcher. `scripts/dev_api.sh --reload` defaults the coupling
off to preserve development hot reload; an explicitly exported setting wins.
`make stop` still signals both processes. Independent deployments can disable
API/worker coupling explicitly; stopping only that API then keeps the worker alive.

Normal ASGI shutdown waits for download BackgroundTasks. Abandoned requests owned
by that API with no active transfer lease become failed/retryable, retaining private
staging. Another API process or a live transfer after a forced timeout is preserved.
Hard OS termination cannot guarantee Python cleanup; child groups are terminated
and reaped where the runtime allows it, and stale state is recovered on restart.

### Hardware facts and uncertainty

`system/info.memory` contains `cpu_name`, `logical_cpu_count`, `total_bytes`,
`available_bytes`, `used_bytes` and `source`. Linux uses `/proc/meminfo`
`MemAvailable` (including reclaimable cache). Other hosts use total RAM from
`sysconf` when available; unknown available/used memory stays null. These are
host facts, not enforced container memory limits. Disk statistics still refer
to `DATA_DIR`; download destination storage checks are a separate workflow.

Device facts include UUID, physical index, PCI address, driver, CUDA availability
and runtime, compute capability, FP16/BF16/FP8 eligibility and `precision_source`.
Precision derived from compute capability is not a successful kernel or model
load test. The worker checks native BF16 through PyTorch in each device's own
context without emulation. FP8 eligibility uses the installed YuE2 runtime's
minimum capability. Unknown readings remain null, including process memory
when NVML cannot report it. Unsupported sensors do not discard other facts.

`loaded_model` is attributed only to the device reported by an online worker's
model manager. `allocated_bytes` / `reserved_bytes` describe the worker's
PyTorch allocator, **not** exact model-only VRAM or audio.cpp subprocess memory.
`memory_source` and `stats_updated_at` distinguish live NVML memory from heartbeat
readings. Worker heartbeats older than 30 seconds, stopped/failed workers,
malformed timestamps and known dead local PIDs are offline. Remote/legacy PIDs
are not checked against the API host. Old heartbeats lacking UUID cannot be
merged safely; restart the worker once to get the new facts.

The recommendation endpoint now returns `capacities`, selected-device `items`,
`by_gpu`, effective `policy` and `scenario`. Legacy `variants` projects the same
model assessments; no fixed benchmark files or parameter counts are fabricated.
`max_model_bytes` is the comfortable heuristic capacity; `max_parameters` is null.
Per-quantization hypothetical capacities live in `capacities[].quantizations`.
Query options: `device_index`, `vae`, `offload_ar`, `compute_backend` and
`budget_gib`. An explicitly missing GPU or invalid scenario returns 422.

Task memory warnings use the same shared model/VAE/cache/runtime estimate, with
`model`, `vae`, `offload_ar` and `compute_backend` query options added to the
existing `/vram-estimate` API. Full waveform decoding reports additional
unprofiled memory rather than claiming the tiled estimate covers it. See
[capacity, statuses, coefficients and uncertainty](model-recommendations.md).

## Models, capabilities and schema

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/models` | Imports recognized legacy installations, refreshes registered paths and returns availability, durable metadata, worker residency and runtime action previews. |
| `GET` | `/api/v1/models/capabilities` | What this installation can do, with a reason for everything it cannot. |
| `GET` | `/api/v1/models/{registry_id}` | Installation metadata, validation report and deletion preview. |
| `POST` | `/api/v1/models/{registry_id}/validate` | Structural validation; JSON body `{"verify_checksum": false}`. `true` also checks weight SHA-256 expectations where provided. |
| `GET` | `/api/v1/models/{registry_id}/deletion-preview` | Exact paths/files, estimated reclaimed space, blockers and confirmation token. |
| `DELETE` | `/api/v1/models/{registry_id}` | JSON body requires `confirmation_token` and `confirmed_path` from the preview. |
| `GET` | `/api/v1/generation/schema` | The parameter registry annotated for the active backend. The frontend renders forms from this. |
| `GET` | `/api/v1/generation/workflow-mapping` | The generated ComfyUI mapping, for the technical drawer. |
| `POST` | `/api/v1/generation/estimate` | Token budget for a request, before it is queued. Takes the same partial config a generation does. |
| `GET` | `/api/v1/generation/limits` | The active checkpoint's own limits, and where each number came from. |

Model inventory includes `download_status`, `files_complete`,
`validation_status`, `registration_status`, `compatibility_status`,
`inference_status`, `inference_ready` and `problem`. `present` remains the legacy
readiness projection. `currently_loaded` is `null` until worker residency can be
established. Metadata such as `parameter_count`, `precision` and `quantization`
is nullable. See [model states](model-setup.md#downloaded-and-available-are-different-states)
for the current validation limits.

`GET /models` additionally projects `runtime` (matching worker model/VAE
snapshots with authoritative worker ID, freshness and online status) and
`runtime_actions.load/unload` (`allowed`, nullable `reason`). These action
previews reuse admission's role, runtime and file checks; they are not a
reservation or an acknowledgement. Concurrent commands, shutdown, memory and
VAE checks can still reject execution. Capability/schema inventories keep their
existing file-only facts. `currently_loaded` on `/models` is true for measured
retained model/VAE tensor placement, including CPU, false for observed absence,
and null for offline/unmeasured/uncertain placement. A lazy VAE is not marked
loaded merely because its model is loaded. GPU residency is exposed separately
as `model_gpu_resident`/`vae_gpu_resident`; it cannot be inferred from that badge.

Local entries add `registry_id`, `aliases`, `created_at`, `updated_at` and nullable
`commit_hash`. `id` remains the legacy directory reference used by task configs;
the registry ID addresses action endpoints and is not a new checkpoint input. The API
reports `registration_status=registered` independently of availability. Unknown
repository defaults remain `discovered`. Registry records persist installation
facts only; readiness and GPU residency are not cached there. Missing entries
remain listed with last known metadata and current file blockers. Corrupt or
unsupported registry documents return `INVALID_CONFIG` (HTTP 422) with recovery
guidance, and are never silently overwritten. See
[registry recovery](model-setup.md#local-model-registry).

Schema options preserve the inventory's `enabled=false` and its reason, including
the configured default. Generation submission reports a missing runtime as
`UNSUPPORTED_CAPABILITY` (HTTP 409), rather than claiming downloaded weights are
missing. Missing required files still use `MODEL_NOT_FOUND` (HTTP 404); selecting
a VAE as the inference checkpoint or invalid installation metadata is
`INVALID_CONFIG` (HTTP 422).

Validation returns HTTP 200 with an explicit `validation` result, including
`validation_status`, compatibility, problem, checked files, hashes and observed
metadata. `validated` means structural checks passed; unavailable runtimes and
incompatible architectures remain separate blockers. Unknown encodings are
`not_validated` with unknown compatibility. Reports expire when the file
fingerprint changes. Native VAE selection/latent-width mismatch is validated
independently of the model. Inventory adds `tensor_element_count`, nullable
`checksum_sha256` and `deletion_status`; tensor elements are not parameter counts.

Deletion is refused with HTTP 409 for task/residency/lease conflicts, external or
protected locations, overlapping installations, or changed confirmation data.
Missing IDs use HTTP 404; missing confirmation fields use HTTP 422. Successful
cleanup returns `deleted=true, complete=true`. Filesystem cleanup failure returns
`deleted=false, complete=false` with an error and retry guidance; the registry
retains a `deleting` journal. Inspect and confirm a fresh preview to retry.
See [validation and deletion](model-setup.md#structural-validation-and-checksums).

### Token budget

```jsonc
{
  "estimate": {
    "risk": "UNSAFE",                      // SAFE | WARNING | UNSAFE
    "exact_tokenisation": true,            // counted with the checkpoint's tokenizer
    "context_tokens": 24576,
    "input_context_tokens": 111,           // instruction, style, lyrics, markers
    "plan_reserve_tokens": 4096,           // held back until the score exists
    "available_generation_tokens": 20166,
    "requested_tokens": 24000,
    "excess_tokens": 3834,
    "max_safe_seconds": 806.6,
    "kv_cache_bytes": 2760998912,
    "reasons": ["The requested 960 s needs 24,000 audio tokens, but only 20,166 are available…"],
    "remedies": ["Reduce the maximum duration to 807 s or less.", "…"]
  },
  "limits": { "context_tokens": 24576, "supports_continuation": false, "sources": {…} }
}
```

`exact_tokenisation: false` means the checkpoint tokenizer could not be loaded
and the figures are approximate; `tokenisation_note` says why. A request whose
risk is `UNSAFE` is refused by `POST /api/v1/generations` with
`TOKEN_BUDGET_EXCEEDED` and the same estimate in `details.budget`.

A capability entry:

```json
{ "supported": false, "reason": "The GPU reports compute capability 8.6; FP8 needs 8.9 or newer." }
```

Each schema parameter also carries `guidance`, the plain-language help the UI
shows behind the ⓘ or ⚠ icon beside its label:

```jsonc
{
  "guidance": {
    "severity": "caution",          // "caution" only where a value really bites
    "what": "The longest the song is allowed to be. The model stops when the song feels finished…",
    "more": "A higher ceiling lets a long song finish instead of being cut off.",
    "less": "A lower ceiling keeps runs short while you are experimenting.",
    "recommended": "Two to three minutes for a full song…",
    "extremes": "If the model reaches the ceiling the result is marked truncated…",
    "cost": "This is the single biggest influence on both generation time and VRAM…"
  }
}
```

Only fields that are true for that parameter are present, so a missing key
means there is nothing useful to say rather than that it has not been written.

A schema parameter carries `enabled`, and `disabled_reason` when it is off:

```json
{
  "key": "synthesis.sampler_name",
  "label": "Sampler",
  "kind": "workflow",
  "enabled": false,
  "disabled_reason": "The native runtime solves the flow-matching ODE with a fixed midpoint solver…",
  "native": { "supported": false, "path": null },
  "comfy": { "node": "KSampler", "widget": "sampler_name" }
}
```

## Projects

A project is the container a song and all of its versions live in. It can be
renamed, reconfigured and deleted; the versions inside it cannot be edited.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/projects` | Every project, each with `generation_count`, `playable_count` and its latest version. |
| `POST` | `/api/v1/projects` | Creates an empty project. |
| `GET` | `/api/v1/projects/{id}` | The project and its complete generation history, newest version first. |
| `PATCH` | `/api/v1/projects/{id}` | Metadata only: `title`, `description`, `style`, `lyrics`, `mode`, `tags`, `favorite`. |
| `GET` | `/api/v1/projects/{id}/config` | The configuration the settings editor should open with, and where it came from. |
| `PUT` | `/api/v1/projects/{id}/config` | Stores the configuration new versions start from. |
| `DELETE` | `/api/v1/projects/{id}` | Deletes the project and every version in it. |

### Renaming

`PATCH` with `{"title": "..."}`. Surrounding and repeated whitespace is
normalised. An empty or whitespace-only name is refused with `422` and
`INVALID_CONFIG`, and the existing name is kept — a project with no name cannot
be found again.

### Configuration

`GET /api/v1/projects/{id}/config` answers with the configuration **and** its
`source`, which is one of:

| `source` | Meaning |
|---|---|
| `project` | The project's own saved settings. |
| `latest_generation` | No saved settings yet, so the most recent version's snapshot is offered. |
| `defaults` | Neither exists, so `configs/yue2.defaults.json` is offered. |

`PUT` takes `{ "config": { … } }`, a partial configuration merged over the
defaults and validated by the same model the generation endpoint uses — an
impossible value is refused here rather than several minutes into a run.

Saving changes only where the project's **next** version starts from. Every
version already generated keeps the snapshot it ran with; nothing under
`projects/<id>/generations/` is rewritten.

### Project deletion

```json
{ "deleted": true, "project_id": "prj_…", "title": "Neon Lane",
  "generations_removed": 3, "generation_ids": ["gen_…", "gen_…", "gen_…"],
  "had_generations": 3, "complete": true, "failures": [] }
```

Only this project's own directory and its own job records are removed; other
projects, the uploads directory and the model files are never involved. As with
a single generation, `complete: false` names what survived instead of claiming a
clean delete. A project containing a queued or running generation is refused with
`409` — cancel it first.

## Generations

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/generations` | Creates and queues. Body: `{ title, project_id?, parent_generation_id?, priority?, config }`. |
| `GET` | `/api/v1/generations` | `project_id, status[], mode, search, favorite, min_duration, max_duration, model, limit, offset`. |
| `GET` / `PATCH` / `DELETE` | `/api/v1/generations/{id}` | PATCH accepts `title` and `favorite`. DELETE is described below. |
| `POST` | `/api/v1/generations/{id}/cancel` | Cooperative. See below. |
| `POST` | `/api/v1/generations/{id}/retry` | Same configuration, new job. |
| `POST` | `/api/v1/generations/{id}/duplicate` | Body is an override object merged over the original. |
| `GET` | `/api/v1/generations/{id}/manifest` | The reproducibility record. |
| `GET` | `/api/v1/generations/{id}/log` | Structured job log. |
| `GET` | `/api/v1/queue` | Active and queued jobs, with the GPU limit. |

`config` is a **partial** configuration merged over `configs/yue2.defaults.json`,
so a request only names what it changes:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/generations \
  -H 'Content-Type: application/json' -d '{
    "title": "City lights",
    "config": {
      "prompt": { "style": "warm piano pop, female vocal, 88 BPM",
                  "lyrics": "[Verse]\nNeon fades along the lane\n[Chorus]\nLet the day come into view",
                  "mode": "full" },
      "sampling": { "max_duration_seconds": 120, "control_after_generate": "randomize" }
    }
  }'
```

The response contains the generation, its project, and any warnings. When the
seed was randomised, the response already carries the concrete seed that will be
used, with `control_after_generate` set back to `fixed` so re-running reproduces
that exact take.

### Versions and lineage

Every generation carries two fields that place it in its project's history:

| Field | Meaning |
|---|---|
| `version` | Its number in the project, from 1. Handed out once and never reused, so deleting version 2 leaves 1 and 3 where they are. |
| `parent_generation_id` | The version this one was started from, or `null`. |

Regeneration is an ordinary `POST /api/v1/generations` carrying the earlier
version's configuration — edited however the user likes — plus its `project_id`
and its id as `parent_generation_id`. A new version is created; the earlier one
is not read from again and never written to. A `parent_generation_id` belonging
to a different project is refused with `422`.

`retry` and `duplicate` do the same thing server-side and record the original as
the parent automatically.

### Deletion

`DELETE /api/v1/generations/{id}` removes the generation, its audio, its score,
its latents, its logs and its manifest, and returns what actually happened:

```json
{ "deleted": true, "generation_id": "gen_…", "artifacts_removed": 9,
  "complete": true, "failures": [] }
```

`complete: false` means some files could not be removed and they are named in
`failures`. Reporting that is the point: claiming a clean delete while files
remain would leave orphans nobody goes looking for. Only that generation's own
directory is touched — model files, shared caches and other projects are never
involved. A running generation is refused with `409`; cancel it first.

### Unfinished generations

A run whose acoustic stage hit its token budget before the song ended settles as
`INCOMPLETE`, never `COMPLETED`, with `error_code: INCOMPLETE_TOKEN_LIMIT` and
`termination_reason: MAX_TOKENS`. The audio is kept and served like any other,
because it is worth hearing, but the status says plainly that it is part of a
song. `budget.semantic` gives the tokens generated against the budget, and the
manifest records the fade applied to the cut.

When the studio raises a limit so a song can finish, the change appears in
`effective_adjustments` with the requested value beside the effective one.
Nothing is ever changed silently.

### Cancellation

`POST .../cancel` returns immediately, but the job does not stop immediately.
A queued job becomes `CANCELLED` straight away because nothing has started. A
running job becomes `CANCEL_REQUESTED` with `cancel_requested: true`, and settles
as `CANCELLED` when the current stage reaches its next safe boundary.

## Artifacts

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/artifacts/{id}` | Artifact list with sizes and SHA-256. |
| `GET` | `/api/v1/artifacts/{id}/audio` | Streams the canonical audio. Range requests supported, so the player can seek. |
| `GET` | `/api/v1/artifacts/{id}/formats` | Which formats this installation can deliver, and the default filename. |
| `GET` | `/api/v1/artifacts/{id}/download?format=&filename=` | The audio as an attachment, converted and renamed on request. |
| `GET` | `/api/v1/artifacts/{id}/file?path=` | Any artifact recorded on that generation. Paths not on the record, and paths outside the data directory, return 404. |

### Download formats

`GET /api/v1/artifacts/{id}/formats` reports every format with whether it can
actually be produced here, because support is decided by asking the installed
FFmpeg which encoders it has rather than by assuming:

```json
{ "source": { "format": "flac", "extension": ".flac", "bytes": 31754561 },
  "default_filename": "YuE2-Neon Lane-v2",
  "ffmpeg": { "path": "/…/tools/ffmpeg/ffmpeg", "present": true },
  "formats": [
    { "id": "flac", "label": "FLAC", "lossless": true, "supported": true,
      "reason": null, "is_source": true, "encoder": "flac" },
    { "id": "mp3", "label": "MP3", "lossless": false, "supported": true,
      "reason": null, "is_source": false, "encoder": "libmp3lame" }
  ] }
```

An unsupported format stays in the list with the reason rather than vanishing.
`is_source` marks the format the master already is.

### Download

`GET /api/v1/artifacts/{id}/download` takes two optional parameters:

| Parameter | Behaviour |
|---|---|
| `format` | `flac`, `wav`, `mp3`, `m4a` or `ogg`. Defaults to the master's own format. An unknown value is refused with `422`. |
| `filename` | The name the browser should save it as, without an extension. |

The master is never modified. Asking for its own format streams that file byte
for byte; asking for another converts a copy into `data/tmp/downloads/`, serves
it, and deletes it when the response finishes. Files from abandoned downloads are
swept after fifteen minutes.

The filename is sanitised on the server, so the query string is a request rather
than a guarantee: directory separators, control characters and Windows reserved
names are removed, the correct extension is appended, and an extension the caller
already typed is not repeated. An empty name falls back to
`<filename_prefix>-<title>-v<version>`.

A conversion that fails or times out deletes its partial output and returns
`ARTIFACT_WRITE_FAILED` with FFmpeg's own message — a download that claims a
format is always that format.

## Scores

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/scores/validate` | Validate arbitrary ABC. |
| `GET` | `/api/v1/scores/{id}` | Source and edited score, each with a validation report. |
| `PUT` | `/api/v1/scores/{id}` | Save an edit. Rejected if the runtime would reject the score. |
| `POST` | `/api/v1/scores/{id}/validate` | Validate the stored score. |
| `POST` | `/api/v1/scores/{id}/compare` | `{ after, before?, voices?, allow_tempo_change? }`. |
| `POST` | `/api/v1/scores/{id}/regenerate` | Queue a run using the edited score. |

`match: true` from a comparison means notes, timing, meter and tempo are
unchanged. Harmony is deliberately allowed to differ — reharmonising is an edit,
not a corruption.

## Presets and uploads

| Method | Path |
|---|---|
| `GET` / `POST` | `/api/v1/presets` |
| `PUT` / `DELETE` | `/api/v1/presets/{id}` (built-ins are read-only) |
| `POST` | `/api/v1/uploads` (multipart audio) |
| `GET` | `/api/v1/uploads/{id}` · `/api/v1/uploads/{id}/audio` |

Uploads accept `.wav .flac .mp3 .ogg .m4a .aiff` up to `MAX_UPLOAD_BYTES`.
Filenames are sanitised and stored under a generated id.

## Live status

**Server-sent events** — `GET /api/v1/generations/{id}/events`. One `status`
event per change, carrying the whole job document, then the stream closes when
the job reaches a terminal state.

**WebSocket** — `GET /ws/jobs/{job_id}`, the same payloads as text frames.

```javascript
const source = new EventSource(`/api/v1/generations/${id}/events`);
source.addEventListener("status", (event) => {
  const job = JSON.parse(event.data);
  // percent is null whenever the stage has no genuine target.
  console.log(job.status, job.progress.label, job.progress.percent ?? job.progress.completed);
});
```

`progress.percent` is populated only for stages with a real target — solver
steps and decoder chunks. Token stages report `completed`, `unit` and
`rate_per_second` with `percent: null`, because a generation limit is a ceiling
rather than a target.
