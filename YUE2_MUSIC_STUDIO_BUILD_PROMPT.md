# YuE2 Music Studio — Professional Build Prompt

## Role

You are a senior AI application architect, ML systems engineer, Python backend engineer, and frontend product engineer.

Build a **local-first, professionally structured AI music-generation application** called **YuE2 Music Studio**.

The application must run on a Linux workstation with:

- NVIDIA RTX A6000
- 48 GB VRAM
- CUDA-capable NVIDIA stack
- Local model files
- No cloud GPU required
- Primary deployment target: one local machine
- Architecture must still be scalable later to multiple GPUs / worker processes

The goal is to provide a polished, Suno-inspired music creation experience while using the open YuE2-3B model locally.

Do **not** copy Suno's source code, branding, proprietary assets, or exact protected visual design. Use only the product interaction concepts as inspiration: simple creation flow, song cards, playable results, custom lyrics/style controls, advanced settings, history/library, generation queue, regeneration, and a modern audio workspace.

---

# 1. Primary Product Goal

Create a web application where a user can:

1. Enter a song idea/style.
2. Enter lyrics or create an instrumental-style request where supported by YuE2.
3. Configure generation settings.
4. Start local generation.
5. Observe generation progress.
6. Listen to the generated result in-browser.
7. View metadata and exact generation settings.
8. Regenerate variations.
9. Save generations to a persistent local library.
10. Download audio.
11. Re-open a previous generation and reproduce it.
12. Optionally use the YuE2 symbolic/ABC workflow.
13. Optionally upload reference audio for the cover workflow.
14. Optionally inspect/edit ABC score data and regenerate from it.
15. Keep generated artifacts, latent/score intermediates where supported, and run metadata organized.

The application is **local-first**. Do not require authentication or a cloud account for the initial version.

---

# 2. Source-of-Truth Hierarchy

Use the following sources in this order:

### Source A — Attached ComfyUI workflow

The attached file:

`yue2_full.json`

is the initial workflow specification.

Treat its actual node names, parameter names, defaults, connections, and workflow behavior as authoritative for the ComfyUI workflow layer.

The workflow contains, among other nodes:

- `EmptyYuE2LatentAudio`
- `KSampler`
- `VAEDecodeAudio`
- `SaveAudioAdvanced`
- `CheckpointLoaderSimple`
- `VAEDecodeAudioTiled`
- `AudioEncoderLoader`
- `SheetSage2AudioToABC`
- `LoadAudio`
- `YuE2GenerateMusic`
- `YuE2GenerateABC`

Its exposed parameters include values such as:

- audio duration / seconds
- batch size
- seed
- seed control mode
- sampling steps
- CFG
- sampler
- scheduler
- denoise
- model checkpoint
- style
- lyrics
- ABC input
- YuE2 generation mode
- max duration
- temperature
- top-p
- top-k
- repetition penalty
- ABC max tokens
- VAE tile size
- VAE overlap
- audio encoder
- output prefix
- output format
- SheetSage2 mode
- uploaded reference audio

Do not lose these parameters when designing the application.

### Source B — YuE repository and current runtime

Use the official YuE repository and current YuE2 runtime documentation to determine the actual supported inference API and runtime behavior.

Repository:

https://github.com/multimodal-art-projection/YuE

The implementation must not blindly emulate ComfyUI internals if the native YuE2 runtime provides a better supported path.

Create an adapter layer so that UI configuration can be mapped to the currently installed YuE2 runtime.

### Source C — YuE2-3B

Model:

https://huggingface.co/m-a-p/YuE2-3B

Use the actual model files locally.

Do not assume cloud-hosted inference.

### Source D — Comfy-Org YuE2 resources

https://huggingface.co/Comfy-Org/YuE2/tree/main

Use this to understand the Comfy-oriented asset/checkpoint arrangement and compare it with the native YuE2 runtime.

### Source E — Suno interaction reference

https://suno.com/

Use Suno only for high-level UX inspiration:

- create flow
- custom mode
- lyrics field
- style field
- song cards
- play controls
- creation history
- advanced controls
- clear primary Create action
- generation-state feedback

Do not clone proprietary implementation or assets.


# 3. Hardware Target

Primary machine:

```text
OS: Linux
GPU: NVIDIA RTX A6000
VRAM: 48 GB
```

The current YuE2 documentation supports a BF16-capable NVIDIA GPU with approximately 24 GB VRAM as a baseline for one active request. Design for one active GPU generation at a time on the A6000, with a persistent queue for additional jobs.

Use the 48 GB VRAM to prefer quality and practical generation length over aggressive quantization, but make precision/backend configurable.

Do not silently change requested parameters to hide OOM.

If an automatic hardware safety adjustment is introduced, show it explicitly in the UI and save both:

- requested configuration
- effective configuration

---

# 5. Recommended Technology Architecture

Use a modular architecture.

## Frontend

Recommended:

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- Zustand only where local UI state is genuinely useful
- native/Web Audio APIs or a robust audio waveform component

Frontend responsibilities:

- presentation
- forms
- validation feedback
- job status
- audio playback
- library browsing
- score editor UI
- settings UI
- API client

Do not place model inference logic in the frontend.

---

# 6. Backend

Recommended:

- Python
- FastAPI
- Pydantic
- initially save on the local folder
- for scaling you can use supabase

Backend responsibilities:

- generation API
- job creation
- validation
- job persistence
- artifact metadata
- model manager
- queue coordination
- workflow adapter
- YuE2 inference service
- optional SheetSage2 service
- audio artifact management
- score management
- WebSocket/SSE progress streaming

Keep the HTTP/API layer separate from inference code.

---

# 7. Worker Architecture

Never execute a long YuE2 inference directly inside a normal HTTP request handler.

Use a job system:

```text
Frontend
   |
   v
FastAPI
   |
   v
Job Database
   |
   v
Local GPU Worker
   |
   +--> YuE2 Planner
   +--> YuE2 Generator
   +--> VAE Decoder
   +--> Optional SheetSage2
   |
   v
Artifact Store
   |
   v
Database Metadata
```

For the first local version:

- SQLite job metadata
- filesystem artifact storage
- an in-process or database-backed queue is acceptable

Design an abstraction so the queue can later be replaced with:

- Redis + RQ
- Celery
- Dramatiq
- another dedicated job system

Do not make Redis mandatory for the first local setup unless it materially improves reliability.

---

# 8. Single-GPU Concurrency Policy

The RTX A6000 is a single-GPU worker target.

Implement:

```text
GPU concurrency = 1 by default
```

Additional jobs become:

```text
QUEUED
```

Never launch multiple large YuE2 generations concurrently by default.

Add configurable worker policy:

```text
max_concurrent_gpu_jobs = 1
```

Make this configurable for future multi-GPU support.

---

# 9. Core Domain Model

Create explicit domain models.

## SongProject

Fields:

- id
- title
- description
- style
- lyrics
- mode
- created_at
- updated_at
- tags
- cover_art_path (optional future field)
- current_generation_id

## GenerationJob

Fields:

- id
- project_id
- status
- queue_position
- requested_at
- started_at
- finished_at
- failed_at
- progress
- stage
- error_code
- error_message
- worker_id

Statuses:

```text
DRAFT
QUEUED
LOADING_MODEL
PLANNING
GENERATING
DECODING
POST_PROCESSING
COMPLETED
FAILED
CANCEL_REQUESTED
CANCELLED
```

## GenerationConfig

Must store every effective parameter.

Example conceptual structure:

```json
{
  "model": {
    "checkpoint": "...",
    "revision": "...",
    "vae": "...",
    "vae_revision": "..."
  },
  "prompt": {
    "style": "...",
    "lyrics": "...",
    "abc": "",
    "mode": "full"
  },
  "sampling": {
    "seed": 17,
    "control_after_generate": "fixed",
    "temperature": 1.0,
    "top_p": 0.95,
    "top_k": 100,
    "repetition_penalty": 1.2
  },
  "planner": {
    "seed": 10,
    "mode": "full",
    "max_abc_tokens": 8192
  },
  "synthesis": {
    "seconds": 120,
    "batch_size": 1,
    "steps": 32,
    "cfg": 1,
    "sampler_name": "dpm_2",
    "scheduler": "sgm_uniform",
    "denoise": 1
  },
  "decoder": {
    "mode": "tiled",
    "tile_size": 1920,
    "overlap": 128
  },
  "output": {
    "format": "flac"
  }
}
```

Do not hard-code these exact defaults as universal truths. Load defaults from a versioned configuration file.

---

# 10. Model Adapter

Create:

```text
backend/
  inference/
    adapters/
      base.py
      yue2_native.py
      comfy_workflow.py
```

Define an interface similar to:

```python
class MusicGenerationBackend(Protocol):
    async def validate_config(...): ...
    async def generate_plan(...): ...
    async def generate_audio(...): ...
    async def decode_audio(...): ...
    async def cancel(...): ...
    async def get_capabilities(...): ...
```

The native YuE2 adapter should be the primary implementation.

The Comfy workflow should be treated as a compatibility/reference layer, not blindly duplicated.

---

# 11. Parameter Mapping Layer

This is one of the most important requirements.

Create a machine-readable schema that maps:

```text
UI parameter
    ->
domain parameter
    ->
YuE2 native parameter
    ->
ComfyUI parameter if applicable
```

Example:

```json
{
  "temperature": {
    "label": "Temperature",
    "group": "Generation",
    "type": "float",
    "min": 0.1,
    "max": 2.0,
    "step": 0.01,
    "native": "temperature",
    "comfy_node": "YuE2GenerateMusic"
  }
}
```

Do this for every configurable parameter.

Never duplicate parameter definitions across many frontend components.

Prefer a backend-served capability/schema endpoint:

```http
GET /api/v1/models/capabilities
GET /api/v1/generation/schema
```

The frontend renders forms from the schema while still allowing custom UX layouts.

---

# 12. Generation Modes

Support the YuE2 concepts that the installed runtime actually exposes.

At minimum design for:

### Full

- style
- lyrics
- symbolic planning
- melody/harmony plan
- audio generation

### Melody

- melody plan
- audio generation
- external melody/ABC support where supported

### Off

- audio generation without symbolic planning where supported

### Cover

Pipeline:

```text
reference audio
   ->
SheetSage2
   ->
ABC / melody representation
   ->
YuE2 melody-conditioned generation
```

### Score Edit

Pipeline:

```text
existing/generated ABC
   ->
user/agent edits
   ->
validation
   ->
YuE2 regeneration
```

Only expose a feature in the UI if the installed backend advertises that capability.

---

# 13. Suno-Inspired UI Structure

Build a dark, modern music-creation interface.

## Main layout

Desktop:

```text
+----------------------------------------------------------+
| Logo | Create | Library | Projects | Settings            |
+-----------------------+----------------------------------+
|                       |                                  |
| Create Music          | Library / Recent Generations     |
|                       |                                  |
| Title                 | Song cards                       |
| Style                 |                                  |
| Lyrics                | [Play] [Download] [More]        |
|                       |                                  |
| Advanced Settings     |                                  |
|                       |                                  |
|       CREATE          |                                  |
+-----------------------+----------------------------------+
| Global queue / current generation status                 |
+----------------------------------------------------------+
```

Mobile:

- bottom navigation
- full-width Create screen
- collapsible advanced settings
- persistent mini-player

---

# 14. Create Screen

The main creation screen should feel simple.

Required controls:

## Title

Optional project/song title.

## Style

Large input.

Helpful examples:

```text
Cinematic Bengali folk-pop, warm male vocal,
acoustic guitar, bamboo flute, organic drums,
melancholic but hopeful, 92 BPM
```

## Lyrics

Large multiline editor.

Support section tags:

```text
[Intro]
[Verse]
[Pre-Chorus]
[Chorus]
[Bridge]
[Outro]
```

Do not invent additional special tags unless supported/documented by the backend.

## Mode

Friendly labels:

- Full Song
- Melody Guided
- Direct Audio
- Cover
- Score Edit

Map them to actual backend capabilities.

---

# 15. Advanced Settings UI

Create collapsible groups.

## Model

- Model/checkpoint
- model revision
- VAE
- VAE revision
- precision/backend if supported
- offline/local-only mode

## Planning

- planning mode
- ABC seed
- ABC max tokens

## Generation

- seed
- seed behavior
- temperature
- top-p
- top-k
- repetition penalty
- max duration

## Diffusion/Acoustic Synthesis

Where supported by the current Comfy workflow/backend:

- steps
- CFG
- sampler
- scheduler
- denoise

## Decoder

- normal decode
- tiled decode
- tile size
- overlap

## Output

- FLAC
- WAV where supported
- MP3 only if implemented as an explicit post-processing conversion

The UI should clearly distinguish:

```text
Model generation parameter
```

from

```text
ComfyUI/workflow execution parameter
```

and

```text
post-processing parameter
```

---

# 16. Reference Audio / Cover UI

Add an optional Reference Audio panel.

Allow:

- drag/drop audio
- file picker
- waveform preview
- duration display
- remove/replace audio

Then:

```text
Reference Audio
    ->
SheetSage2 transcription
    ->
ABC preview
    ->
editable score
    ->
YuE2 generation
```

Show transcription warnings to the user.

Do not pretend the transcription is guaranteed to be exact.

---

# 17. ABC / Score Editor

The architecture should support an expandable score workspace.

Required in MVP:

- display raw ABC
- edit raw ABC
- validate ABC
- save source score
- save edited score
- compare source vs edited score
- regenerate from edited score

Future:

- visual staff notation
- piano-roll
- agentic score editing

Do not block MVP on a graphical music notation editor.

---

# 18. Generation Progress UI

Never show a fake percentage.

Progress must come from actual backend stages.

Example:

```text
Queued
Loading model
Planning composition
Generating audio
Decoding
Saving artifacts
Complete
```

If the exact percent is unavailable, show stage-based progress:

```text
Generating audio...
```

and optionally an indeterminate progress indicator.

When the backend knows segment/session progress, expose it.

---

# 19. Result Card

Each completed generation should provide:

- title
- duration
- style summary
- creation timestamp
- model
- seed
- mode
- audio player
- waveform
- play/pause
- seek
- volume
- download
- regenerate
- duplicate config
- open project
- view score
- view generation settings

Provide a compact "Technical details" drawer.

---

# 20. Generation Library

Create a local library.

Views:

- Recent
- Projects
- Favorites
- Failed generations
- Saved scores

Filters:

- date
- style/tag
- generation mode
- duration
- model

Search:

- title
- style
- lyrics
- tags

---

# 21. Reproducibility

This is mandatory.

Every generation must save a manifest.

Example:

```json
{
  "schema_version": 1,
  "generation_id": "...",
  "created_at": "...",
  "runtime_version": "...",
  "model_id": "m-a-p/YuE2-3B",
  "model_revision": "...",
  "vae_id": "m-a-p/YuE2-Vae",
  "vae_revision": "...",
  "model_hash": "...",
  "request": {},
  "effective_config": {},
  "hardware": {
    "gpu": "...",
    "vram_bytes": 0,
    "cuda": "...",
    "torch": "..."
  }
}
```

Save enough information to explain exactly what produced a result.

---

# 22. Artifact Storage

Use a deterministic directory structure.

Example:

```text
data/
  projects/
    <project-id>/
      project.json
      generations/
        <generation-id>/
          request.json
          effective_config.json
          manifest.json
          score/
            source.abc
            edited.abc
          audio/
            final.flac
          intermediates/
            latent/
          logs/
            generation.log
```

Do not put large binary blobs into SQLite.

Database stores metadata and artifact paths.

---

# 23. Audio Processing

Use reliable Python audio tooling.

Required:

- WAV/FLAC reading and writing
- duration detection
- sample-rate metadata
- channel metadata

FFmpeg may be used for optional conversion.

Do not re-encode unnecessarily.

Keep the model's native output untouched as the canonical artifact.

---

# 24. API Design

Use versioned APIs.

Example:

```text
/api/v1/health
/api/v1/system/info
/api/v1/models
/api/v1/models/capabilities

/api/v1/projects
/api/v1/projects/{id}

/api/v1/generations
/api/v1/generations/{id}
/api/v1/generations/{id}/cancel
/api/v1/generations/{id}/retry
/api/v1/generations/{id}/duplicate

/api/v1/artifacts/{id}

/api/v1/scores/{id}
/api/v1/scores/{id}/validate
/api/v1/scores/{id}/compare
```

For real-time status:

```text
/ws/jobs/{job_id}
```

or Server-Sent Events.

---

# 25. Validation

Validate at both frontend and backend.

Examples:

- seed integer/range
- duration range
- temperature bounds
- top-p bounds
- top-k integer
- repetition penalty valid range
- batch size
- steps
- CFG
- sampler exists
- scheduler exists
- model exists
- VAE exists
- referenced audio exists
- ABC is parseable when required
- lyrics not excessively large
- impossible combinations are rejected

Do not trust frontend validation.

---

# 26. Hardware Monitoring

Provide a System Info page:

```text
GPU
GPU memory total
GPU memory used
GPU memory free
CUDA version
PyTorch version
YuE2 runtime version
Loaded model
Worker state
Queue length
Disk space
```

Use NVML/PyNVML or a similarly reliable local mechanism.

The UI should warn:

```text
GPU memory may be insufficient for the requested duration/configuration.
```

before starting when the backend can estimate risk.

---

# 27. Model Lifecycle

Implement a Model Manager.

Responsibilities:

- detect local models
- verify model files
- load model lazily
- keep model loaded between jobs
- unload when configured
- expose memory state
- validate model revision
- expose capabilities

Do not reload a 7+ GB model for every request.

The YuE2-3B model repository currently contains a `model.safetensors` file of roughly 7.26 GB, so repeated loading would be unnecessarily expensive.

---

# 28. Environment Configuration

Use `.env`.

Example:

```env
APP_ENV=development

BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000

FRONTEND_URL=http://127.0.0.1:3000

YUE2_MODEL_PATH=/models/YuE2-3B
YUE2_VAE_PATH=/models/YuE2-Vae

SHEETSAGE2_MODEL_PATH=/models/SheetSage2

DATA_DIR=./data

CUDA_VISIBLE_DEVICES=0

MAX_CONCURRENT_GPU_JOBS=1
```

Never hard-code model paths.

---

# 29. Python Environment Strategy

Prefer a dedicated Python environment for YuE2.

Because some auxiliary components may have different dependency requirements, keep them isolated where needed.

Example architecture:

```text
apps/
  web/

services/
  api/
  yue2-worker/
  sheetsage2-worker/   # optional separate env/process

packages/
  generation-schema/
  shared-types/
```

A practical local installation may use:

```text
.venv-yue2
.venv-sheetsage2
```

if their dependency versions conflict.

Do not force every model into one Python environment if that makes the runtime fragile.

---

# 30. Development Structure

Recommended monorepo:

```text
yue2-music-studio/
├── apps/
│   └── web/
│       ├── app/
│       ├── components/
│       ├── features/
│       ├── hooks/
│       ├── lib/
│       └── types/
│
├── services/
│   ├── api/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── core/
│   │   │   ├── db/
│   │   │   ├── domain/
│   │   │   ├── schemas/
│   │   │   ├── services/
│   │   │   └── main.py
│   │
│   ├── yue2_worker/
│   │   ├── adapters/
│   │   ├── engine/
│   │   ├── jobs/
│   │   ├── model_manager/
│   │   └── worker.py
│   │
│   └── sheetsage2_worker/
│
├── packages/
│   ├── config-schema/
│   ├── shared-types/
│   └── workflow-schema/
│
├── configs/
│   ├── yue2.defaults.json
│   ├── yue2.capabilities.json
│   └── workflow-mapping.json
│
├── scripts/
├── tests/
├── docs/
├── data/
├── docker/
├── .env.example
├── Makefile
└── README.md
```

---

# 31. Dependency Strategy

Pin critical versions.

At minimum record:

- Python
- PyTorch
- CUDA
- Transformers
- YuE2 runtime
- safetensors
- accelerate
- frontend dependencies

Do not install "latest everything".

Use lock files where practical.

---

# 32. Docker Strategy

The app must run natively on Linux first.

Docker is optional.

If Docker is provided:

- support NVIDIA Container Toolkit
- expose GPU
- mount model directory
- mount data directory
- do not rebuild multi-GB model weights into every image layer

Provide both:

```text
native development
```

and

```text
optional Docker deployment
```

---

# 33. Logging and Error Handling

Use structured logs.

Every job should have:

```text
job_id
generation_id
stage
timestamp
severity
message
```

Errors should be categorized:

```text
MODEL_NOT_FOUND
MODEL_LOAD_FAILED
CUDA_OOM
INVALID_CONFIG
INVALID_ABC
AUDIO_INPUT_ERROR
INFERENCE_FAILED
DECODER_FAILED
ARTIFACT_WRITE_FAILED
CANCELLED
UNKNOWN
```

For CUDA OOM:

- preserve the requested config
- report which stage failed
- show useful guidance
- never silently downgrade settings

---

# 34. Testing

Write tests for:

### Backend unit tests

- config validation
- parameter mapping
- job state machine
- manifest generation
- artifact paths
- queue behavior

### Integration tests

- API -> job
- job -> mock worker
- artifact retrieval
- WebSocket/SSE progress

### Model smoke test

A real GPU test that:

1. loads the model
2. generates a short test
3. decodes audio
4. verifies output file
5. records VRAM peak
6. records elapsed time

Do not run large generations in unit tests.

---

# 35. Security

Although local-only, follow sane practices:

- bind to localhost by default
- restrict allowed upload file types
- sanitize filenames
- prevent path traversal
- limit upload size
- avoid executing user-supplied shell commands
- never pass raw user input into shell strings
- isolate model operations from API process where practical

If network exposure is later enabled, add authentication before recommending it.

---

# 36. UX Quality Requirements

The application must not feel like a developer dashboard.

It should feel like a music product.

Use:

- spacious layout
- strong typography
- clear hierarchy
- modern cards
- waveform visualization
- micro-interactions
- skeleton loading
- keyboard accessibility
- responsive design
- meaningful empty states
- clear error messages

Avoid:

- giant JSON editors as the primary UI
- exposing internal node IDs
- requiring users to understand ComfyUI terminology
- stuffing every parameter on the first screen

Advanced users must still have access to every supported parameter through an Advanced Settings panel.

---

# 37. Presets

Implement presets.

Examples:

```text
Balanced
High Quality
Fast Preview
Custom
```

A preset is just a saved configuration object.

Users can:

- select preset
- modify it
- save as preset
- duplicate preset
- reset to default

Do not make presets separate hidden logic.

---

# 38. Seed Management

Support:

```text
Fixed
Randomize
Increment
```

or the exact supported behavior of the underlying backend.

When "Randomize" is used:

- generate seed server-side
- display the final seed
- save it to manifest

---

# 39. Queue UX

Bottom/right queue drawer:

```text
Generating: My Song
Queued: 2
```

Each job:

- priority
- status
- elapsed time
- cancel
- retry
- open result

Keep queue state persistent across frontend refreshes.

---

# 40. Cancelation

Cancellation is difficult for native ML inference.

Implement cooperative cancellation:

- job has cancel flag
- worker checks at safe boundaries
- subprocess termination can be added if required
- never claim immediate cancellation unless guaranteed

UI should show:

```text
Cancellation requested...
```

before final cancellation state.

---

# 41. Future Scalability

The application must be able to evolve to:

```text
1 GPU
   ->
multiple local GPUs
   ->
multiple worker machines
   ->
remote API workers
```

Do this by separating:

- API
- queue
- worker
- model runtime
- artifact storage

Never assume the worker is on the same machine as FastAPI.

---

# 42. Performance Strategy

Optimize in this order:

1. keep model loaded
2. reuse tokenizer/model state
3. avoid duplicate decoding
4. stream status
5. avoid unnecessary file copies
6. use efficient audio encoding
7. use GPU memory monitoring
8. profile before introducing exotic optimizations

Do not prematurely introduce distributed inference.

---

# 43. Product Roadmap

## Phase 1 — Foundation

- repo structure
- local environment
- model loading
- basic YuE2 generation
- FastAPI
- Next.js
- one GPU worker
- SQLite
- file artifacts

## Phase 2 — Suno-like creator

- Create screen
- style
- lyrics
- title
- advanced settings
- audio player
- generation queue
- library

## Phase 3 — Workflow completeness

- ABC planning
- score view/edit
- cover upload
- SheetSage2 integration
- tiled decoder controls
- artifact manifests

## Phase 4 — Professionalization

- presets
- project pages
- reproducibility
- system monitoring
- robust logs
- error taxonomy
- benchmarks
- automated tests

## Phase 5 — Scale

- Redis queue
- multiple workers
- multiple GPUs
- Postgres
- object storage abstraction
- remote worker support

---

# 44. Required First Deliverables From the Coding Agent

Do not immediately generate the entire application in one uncontrolled pass.

First produce:

### A. Architecture document

Include:

- system diagram
- module responsibilities
- database schema
- API contract
- worker lifecycle
- artifact structure
- parameter mapping strategy
- model lifecycle

### B. Repository scaffold

Create the monorepo structure.

### C. Local setup

Provide exact commands for Linux + NVIDIA GPU.

### D. YuE2 smoke test

Verify that the local model can generate audio outside the web UI.

### E. Backend MVP

Implement:

- health
- system info
- generation request
- queue
- job status
- artifact listing

### F. Frontend MVP

Implement:

- Create page
- advanced settings
- progress
- result player
- library

Only then continue to advanced workflows.

---

# 45. Exact Implementation Behavior

When writing code:

- use strong typing
- use Pydantic models
- use explicit interfaces
- prefer dependency injection for services
- avoid global mutable state
- use async I/O in API layer
- isolate blocking GPU work in worker process
- write docstrings for non-obvious inference code
- keep model integration in dedicated modules
- avoid importing frontend-specific concepts into backend
- avoid embedding workflow JSON directly into React components

---

# 46. Important Native-vs-Comfy Rule

The attached ComfyUI JSON is a crucial reference, but it is not automatically equivalent to the native YuE2 Python API.

Therefore:

1. Parse the workflow.
2. Extract exposed parameters.
3. Build the application schema around those capabilities.
4. Inspect the installed YuE2 runtime.
5. Map parameters where a true native equivalent exists.
6. Mark Comfy-specific parameters separately.
7. Never fake unsupported functionality.
8. If a UI parameter cannot be applied to the native backend, disable it with an explanation instead of silently ignoring it.

Provide a backend capability object such as:

```json
{
  "parameter": "sampler_name",
  "supported": true,
  "backend": "comfy",
  "native_equivalent": null
}
```

or:

```json
{
  "parameter": "temperature",
  "supported": true,
  "backend": "native",
  "native_equivalent": "temperature"
}
```

---

# 47. Observability

Expose:

- generation latency
- planning latency
- decoding latency
- queue wait time
- GPU memory peak
- output duration
- failures by stage

Store metrics so the developer can later optimize the worker.

---

# 48. Documentation Requirements

Produce:

```text
README.md
docs/architecture.md
docs/setup-linux.md
docs/model-setup.md
docs/parameter-guide.md
docs/api.md
docs/troubleshooting.md
docs/licensing.md
docs/cover-workflow.md
docs/score-editing.md
```

The parameter guide must explain each UI parameter in beginner-friendly language.

---

# 49. Developer Experience

Provide commands such as:

```bash
make install
make dev
make backend
make frontend
make worker
make test
make lint
make format
make smoke-test
```

Also provide direct commands for developers who do not use Make.

---

# 50. Final Acceptance Criteria

The project is acceptable only when all of the following work on the local RTX A6000:

1. Start backend.
2. Start frontend.
3. Detect GPU.
4. Detect local YuE2 model.
5. Open Create page.
6. Enter style and lyrics.
7. Select generation settings.
8. Submit generation.
9. Queue job.
10. Generate using local GPU.
11. Decode audio.
12. Save FLAC/WAV artifact as configured.
13. Stream progress.
14. Display generated result.
15. Play result.
16. Download result.
17. Save manifest.
18. Reopen generation from Library.
19. Duplicate generation configuration.
20. Regenerate.
21. View exact seed and parameters.
22. Use Advanced Settings without editing source code.
23. Use ABC planning when supported.
24. Use cover workflow when SheetSage2 is installed and supported.
25. Persist data after application restart.
26. Fail gracefully on OOM and invalid configuration.
27. Keep all model/runtime versions recorded.

---

# 51. Final Instruction to the Coding Agent

Before coding, inspect:

- the attached `yue2_full.json`
- the official YuE repository
- the YuE2-3B model card/files
- current YuE2 generation documentation
- the actual installed/runtime API
- the model and dependency licenses

Then create the architecture and repository scaffold.

Do not make assumptions where source material can be inspected.

When a mismatch exists between the ComfyUI workflow and the native runtime, preserve the distinction and implement an adapter.

The final product should be a **local-first YuE2 music creation studio**, not a thin wrapper around a shell command and not a hard-coded ComfyUI clone.

Prioritize:

**correctness -> reproducibility -> clean architecture -> UX quality -> performance -> extensibility.**
