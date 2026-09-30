# API

Base URL `http://127.0.0.1:8000`. Interactive documentation at `/docs`.

## Model setup

- `GET /api/v1/system/model-recommendation` ranks supported YuE2 GGUF variants for the selected GPU.
- `GET /api/v1/models/hub?repo_id=owner/name&revision=main` lists remote GGUF and safetensors files.
- `POST /api/v1/models/downloads` accepts `{ "repo_id": "owner/name", "filename": "file.gguf", "revision": "main" }` and returns a download ID.
- `GET /api/v1/models/downloads` and `GET /api/v1/models/downloads/{id}` report file progress, completion, and failures. Completed compatible models appear in the existing model inventory and generation schema.

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
| `GET` | `/api/v1/system/info` | GPUs (NVML), disk, queue, worker heartbeat, runtime versions. |
| `GET` | `/api/v1/system/vram-estimate` | `?seconds=&decoder_mode=&budget_gib=` — returns a warning or `null`. An estimate, clearly labelled as one; it never changes the request. |
| `GET` | `/api/v1/system/gpus` | Selectable GPUs, which one is chosen, and which one the worker is using right now. |
| `PUT` | `/api/v1/system/device` | `{"device_index": 1}` — choose the GPU. Applies to the next job; a run in flight finishes where it started. |

### Choosing a GPU

The device list comes from the worker, not from the API's own NVML query,
because `CUDA_VISIBLE_DEVICES` can hide cards from the worker that NVML still
sees — offering an index the worker cannot address would not be a real choice.
When that variable is set, live utilisation is not merged into the list rather
than being attributed to the wrong card, and `note` explains why.

```jsonc
{
  "selected_index": 1,          // what the System page has chosen
  "active_index": 0,            // what the worker is using at this moment
  "pending_restart": true,      // the model reloads on the next job
  "devices": [
    { "index": 0, "name": "NVIDIA RTX A6000", "memory_free_bytes": 13207764992,
      "other_process_count": 1, "other_process_bytes": 37346082816, "selected": false }
  ]
}
```

The choice is stored in `data/runtime-settings.json`, so it survives a restart
and does not require editing `.env`.

## Models, capabilities and schema

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/models` | Imports recognized legacy installations, refreshes registered paths and returns live availability alongside durable metadata. |
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
