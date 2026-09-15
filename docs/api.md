# API

Base URL `http://127.0.0.1:8000`. Interactive documentation at `/docs`.

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

## Models, capabilities and schema

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/models` | Local weight directories and whether they exist. |
| `GET` | `/api/v1/models/capabilities` | What this installation can do, with a reason for everything it cannot. |
| `GET` | `/api/v1/generation/schema` | The parameter registry annotated for the active backend. The frontend renders forms from this. |
| `GET` | `/api/v1/generation/workflow-mapping` | The generated ComfyUI mapping, for the technical drawer. |

A capability entry:

```json
{ "supported": false, "reason": "The GPU reports compute capability 8.6; FP8 needs 8.9 or newer." }
```

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

| Method | Path |
|---|---|
| `GET` / `POST` | `/api/v1/projects` |
| `GET` / `PATCH` / `DELETE` | `/api/v1/projects/{id}` |

`GET /api/v1/projects/{id}` returns the project and all of its generations.

## Generations

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/generations` | Creates and queues. Body: `{ title, project_id?, priority?, config }`. |
| `GET` | `/api/v1/generations` | `project_id, status[], mode, search, favorite, min_duration, max_duration, model, limit, offset`. |
| `GET` / `PATCH` / `DELETE` | `/api/v1/generations/{id}` | PATCH accepts `title` and `favorite`. |
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
| `GET` | `/api/v1/artifacts/{id}/download` | Same bytes as an attachment. |
| `GET` | `/api/v1/artifacts/{id}/file?path=` | Any artifact recorded on that generation. Paths not on the record, and paths outside the data directory, return 404. |

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
