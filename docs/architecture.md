# Architecture

## System

```text
┌──────────────────────────────────────────────────────────────────┐
│ apps/web — Next.js 15, TypeScript, Tailwind, TanStack Query      │
│ Create · Library · Projects · Generation · Score · System        │
└───────────────┬──────────────────────────────────┬───────────────┘
                │ REST /api/v1                     │ SSE + WebSocket
                ▼                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│ services/api — FastAPI (.venv-api, no torch)                     │
│  api/v1/       routes, thin                                      │
│  services/     GenerationService, CapabilityService, SystemInfo  │
│  core/         dependency providers, error envelope, logging     │
└───────────────┬──────────────────────────────────────────────────┘
                │ writes a job document
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ data/jobs/<job-id>.json   +  data/jobs/.queue.lock (flock)       │
└───────────────┬──────────────────────────────────────────────────┘
                │ claimed under the lock, one at a time
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ services/yue2_worker — (.venv-yue2: torch 2.10 + yue2-infer)     │
│  ModelManager        keeps the 7.26 GB checkpoint resident       │
│  adapters/           yue2_native · mock · comfy_workflow         │
│  jobs/reporter.py    writes real stage progress back to the job  │
│  engine/artifacts.py audio, score, latents, manifest             │
└───────────────┬──────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ data/projects/<project>/generations/<generation>/                │
│   request.json effective_config.json manifest.json job.json      │
│   audio/  score/  intermediates/  logs/                          │
└──────────────────────────────────────────────────────────────────┘
```

`packages/core` (`yue2_studio_core`) is imported by both Python processes and
holds the domain models, the settings, the filesystem store, the queue
interface, the parameter registry loader, the manifest builder and the vendored
ABC parser. It depends on pydantic and nothing heavier.

## Why three processes

* A long inference must never occupy an HTTP worker. The API returns as soon as
  the job document is on disk.
* The runtime pins `torch==2.10.0` and `transformers==4.57.6`. Keeping those out
  of the API environment means an API dependency bump cannot break inference.
* The worker communicates only through the data directory, so moving it to
  another machine is a matter of sharing that directory. Nothing in the API
  assumes the worker is local.

## Storage

There is no database. The layout is deterministic and self-describing:

```text
data/
  projects/<project-id>/project.json
  projects/<project-id>/generations/<generation-id>/
      request.json           what the user asked for
      effective_config.json  what the runtime actually used
      manifest.json          the full reproducibility record
      job.json               a copy of the job document
      failure.json           written only when a run fails or is cancelled
      audio/final.flac       the runtime's own output, never re-encoded
      audio/final.mp3        optional delivery copy
      score/source.abc       the planner's score
      score/edited.abc       your edits
      score/score.json
      intermediates/latent.npy semantic.npy
      logs/generation.log    one JSON object per line
  runtime-settings.json      user settings changed from the UI (selected GPU)
  jobs/<job-id>.json         queue and status
  jobs/<job-id>.cancel       cancellation marker (see below)
  jobs/.queue.lock           advisory lock
  uploads/<upload-id>/
  presets/<preset-id>.json
  worker/<worker-id>.json    heartbeat: state, model, GPU, versions
```

Writes are atomic: a temporary file then `os.replace`. A crash mid-write leaves
the previous version intact, never a truncated one.

Large binaries never enter a JSON document. The job records paths, sizes and
SHA-256 hashes; the bytes stay on the filesystem.

## Queue and concurrency

`FilesystemJobQueue` implements the `JobQueue` protocol. `claim()` takes an
exclusive `flock` on `data/jobs/.queue.lock`, sorts queued jobs by
`(-priority, requested_at)`, and hands out the first one only if the worker is
below `MAX_CONCURRENT_GPU_JOBS` (default 1). Everything else stays `QUEUED`.

Replacing this with Redis/RQ, Celery or Dramatiq means writing another class
with the same five methods. No route, service or worker stage reaches for the
filesystem directly.

## Job state machine

```text
DRAFT ─► QUEUED ─► LOADING_MODEL ─► [TRANSCRIBING] ─► PLANNING ─► GENERATING ─► DECODING
                                                                 │
                                                                 ▼
                                                        POST_PROCESSING
                                                                 │
                                                                 ▼
                                                            COMPLETED

any active state ─► FAILED
QUEUED           ─► CANCELLED           (nothing started; immediate)
active           ─► CANCEL_REQUESTED ─► CANCELLED
```

`TRANSCRIBING` occurs only for covers, where the reference recording is turned
into a melody score before the YuE2 weights are loaded, so the two models are
never resident on the same card at once.

`ALLOWED_TRANSITIONS` in `packages/core/yue2_studio_core/models.py` is the only
definition of this; the API and the worker both check against it.

### Cancellation

Cancellation is cooperative and is never described as immediate.

1. The API writes `data/jobs/<id>.cancel` and sets `cancel_requested` on the job.
2. A watcher thread in the worker polls for that marker every
   `CANCEL_POLL_INTERVAL_SECONDS` and sets a `threading.Event`.
3. The event backs the `cancelled` callable that `yue2` checks between tokens,
   solver steps and decoder chunks. The stage stops at its next safe boundary.
4. The job settles as `CANCELLED` with `error_code: CANCELLED`, and
   `failure.json` preserves the configuration that was requested.

The marker is a separate file on purpose. The worker rewrites the job document
continuously while reporting progress; if the request lived only in that
document, the worker's next write from its in-memory copy would erase it.

## Backend adapters

`services/yue2_worker/adapters/base.py` defines the contract:

```python
async def get_capabilities() -> dict
async def validate_config(config) -> list[str]      # warnings, or raise
async def prepare(config, context)                  # load or reuse weights
async def generate_plan(context) -> PlanResult
async def generate_audio(context, plan) -> AudioTokensResult
async def decode_audio(context, tokens) -> DecodedAudio
async def finalise(context, plan, tokens, audio) -> BackendResult
async def cancel(job_id)
async def shutdown()
```

| Adapter | Role |
|---|---|
| `yue2_native` | Primary. Drives `YuE2Pipeline` stage by stage. |
| `mock` | No GPU. Exercises the whole application; labels itself as mock in every manifest. |
| `comfy_workflow` | Compatibility layer. Patches `yue2_full.json` from the generated mapping and submits it to a ComfyUI server. |

The native adapter also drives `services/sheetsage2_worker`, a transcription
service in its own environment. SheetSage2 pins torch 2.8.0 and transformers
4.45.2 against YuE2's 2.10.0 and 4.57.6, so it runs as a subprocess and the two
exchange a JSON report and a score file. It is launched with an argument list,
never a shell string, and pinned to the selected card with
`CUDA_VISIBLE_DEVICES`.

Blocking GPU calls run through `asyncio.to_thread`, so the worker's event loop
keeps servicing its heartbeat and cancellation watcher while the GPU is busy.

### Progress integration with the runtime

`YuE2Pipeline` routes every stage through `_status`, a context manager yielding
a progress handle. The pipeline is constructed with `progress=False` so nothing
reaches stderr, then `progress` is re-enabled and `_status` is replaced with an
instance-level implementation that forwards to the studio's reporter. That is
the single integration seam; no runtime behaviour, RNG state or configuration is
touched. It gives real counts for `Planning score` and `Generating song`, and
real totals for `Synthesizing audio` (solver steps) and `Decoding audio`
(chunks).

## Model lifecycle

`ModelManager` keys the resident pipeline on everything that would force a
rebuild: **device index**, model, revision, decoder, backend, quantization, AR
offload, memory budget, offline flag, decoder tile size and solver steps.
Sampling is deliberately *not* in the key — it travels with each request, so
changing a temperature never reloads 7 GB, and a resident pipeline can never
apply a previous job's token budget to the next one.

The device index is read fresh from `data/runtime-settings.json` on every job,
which is how the System page can move the model to another GPU without a
restart. A job whose key
matches reuses the loaded model; a job that differs tears the old one down
first. `MODEL_IDLE_UNLOAD_SECONDS=0` (the default) keeps it resident forever.
File existence and `config.json`/`model.safetensors` presence are checked before
loading, so a missing model fails as `MODEL_NOT_FOUND` rather than deep inside
the runtime.

## Parameter mapping

`configs/parameter-registry.json` is the only place a parameter is defined:
UI label and help, type and range, `kind` (model / workflow / post /
studio), the native path, and the ComfyUI node and widget.

`scripts/` regenerates `configs/workflow-mapping.json` from that registry plus
`yue2_full.json`, and a test asserts the generated values still match the
workflow. Six parameters have no native equivalent and say so:

| Parameter | ComfyUI node | Why there is no native equivalent |
|---|---|---|
| `planner.seed` | `YuE2GenerateABC.seed` | The native pipeline derives both stages from one request seed. |
| `synthesis.sampler_name` | `KSampler.sampler_name` | The runtime solves the flow-matching ODE with a fixed midpoint solver. |
| `synthesis.scheduler` | `KSampler.scheduler` | Uniform midpoint schedule; nothing to choose. |
| `synthesis.denoise` | `KSampler.denoise` | The full trajectory is always solved; no partial-denoise entry point. |
| `synthesis.seconds` | `EmptyYuE2LatentAudio.seconds` | Latents are sized from the tokens the model emitted; nothing is preallocated. |
| `synthesis.batch_size` | `EmptyYuE2LatentAudio.batch_size` | One call, one candidate. Queue several jobs for variations. |

Conversely, `steps` → `ode_steps`, `cfg` → `cfg_scale`, `max_duration` →
`semantic.max_tokens`, `tile_size` → `vae_core_frames` and `max_abc_tokens` →
`abc.max_tokens` are true equivalents and are wired through.

## The duration/token relationship

The decoder's `sample_rate` is 48000 and its `downsampling_ratio` is 1920, so
there are exactly **25 latent frames per second**, and the acoustic stage emits
one codec token per latent frame. Therefore:

```text
seconds = semantic_max_tokens / 25
```

That is why the runtime default of 9000 tokens and the workflow's
`max_duration = 360` describe the same limit, and it is why the UI can offer a
duration slider that maps onto a token budget without inventing anything. A
30-second request produced exactly 29.9987 s of audio in testing — 750 tokens.

## Errors

Every failure carries a code from `ErrorCode` and guidance written for the
person reading it. `CUDA_OOM` preserves the requested configuration, names the
stage that failed and suggests what to change. Nothing is ever downgraded and
retried silently.
