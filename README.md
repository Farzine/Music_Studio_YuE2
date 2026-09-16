# YuE2 Music Studio

A local-first music creation studio built on the open **YuE2-3B** model. Style and
lyrics go in, a full song comes out, and every version keeps the exact settings,
the symbolic score and a manifest that explains what produced it.

Everything runs on one machine. No cloud GPU, no account, no database — projects,
audio, scores and logs are ordinary files under `data/`.

---

## What works today

Verified on the target hardware (NVIDIA RTX A6000, 48 GB, driver 560.28.03):

| | |
|---|---|
| Runtime | `yue2-infer` 0.1.6, torch 2.10.0+cu126, transformers 4.57.6 |
| Model | `m-a-p/YuE2-3B` (7.26 GB) + `m-a-p/YuE2-Vae` |
| Output | 48 kHz stereo, 24-bit FLAC (or WAV; MP3 as an explicit conversion) |
| Measured | 30 s of audio in 28.6 s wall clock, 7.24 GiB peak VRAM |
| Stages | transcribe (covers), plan, acoustic tokens, synthesis, decode — each reported separately |
| Limits | 24,576-token window read from the checkpoint; 25 tokens per second of audio, so roughly 13–16 minutes of song once the prompt is subtracted |
| GPUs | every card is listed on the System page with its free memory; pick one there, no restart |
| Downloads | FLAC, WAV, MP3, M4A and OGG, offered only when the installed FFmpeg can actually write them |

Modes: **Full Song**, **Melody Guided**, **Direct Audio**, **Score Edit** and
**Cover**. Cover transcribes a recording you supply into a melody score with
SheetSage2 and realises it in your style; install it with `make cover` and the
System page will show it switched on. Anything not installed stays visible but
disabled with the specific reason, rather than quietly missing.

---

## Features

**Music generation**

- Text-to-music from a style description and lyrics, on your own GPU.
- Five generation modes, including covering a recording you supply.
- An editable ABC score between planning and audio, so you can change the tune
  before it is performed.
- 48 parameters, every one of them explained in plain language in the UI.
- A live token budget that says, before you spend GPU time, whether the song
  you asked for fits.

**Project management**

- Projects group every version of one song.
- Rename a project.
- Edit a project's generation configuration — every supported parameter, on one
  page — which becomes the starting point for its next version.
- Delete a project, with a confirmation that names what goes with it.

**Generation history**

- A complete history per project, newest version first, numbered from 1.
- Each version shows its date, status, duration, model, seed, mode and prompt,
  and where it was regenerated from.
- Play, regenerate, rename, download or delete any single version.
- Deleting one version never touches the others.

**Regeneration**

- Regenerate loads a version's complete configuration into an editable form.
- Every parameter stays editable before you generate.
- Generating creates a **new** version. The one you started from is never
  overwritten, and its stored configuration never changes.

**Audio**

- Built-in player with a waveform, seeking and a persistent player bar.
- A download dialog with format selection and a custom filename.
- Format conversion through FFmpeg, leaving the original file untouched.

**Everything else**

- Real progress only: no invented percentages.
- A reproducibility manifest per generation, including weight hashes.
- Pick which GPU runs the model, from the System page, without a restart.
- Cooperative cancellation of a running job.
- Responsive layout, keyboard-reachable help, light and dark themes.

---

## Technology Stack

| Layer | What is actually used |
|---|---|
| Frontend | Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4, Radix UI, TanStack Query, Zustand, lucide-react |
| Backend API | Python 3.11, FastAPI, Pydantic v2, pydantic-settings, Uvicorn |
| GPU worker | Python 3.12, PyTorch 2.10.0+cu126, `yue2-infer` 0.1.6, transformers, soundfile, NVML |
| Model | `m-a-p/YuE2-3B` with the `m-a-p/YuE2-Vae` decoder |
| Transcription (optional) | SheetSage2 + MERT-v2-FullSong, in a separate Python environment |
| Audio processing | soundfile for writing the master; FFmpeg for delivery conversions |
| Storage | The filesystem. JSON documents and audio files under `DATA_DIR`. **No database.** |
| Queue | A directory of JSON job documents serialised with an advisory file lock |
| Authentication | None. The studio binds to `127.0.0.1` and is meant for one machine. |

---

## Project Structure

```text
Music_Studio_YuE2/
│
├── apps/web/                  # Next.js frontend
│   ├── app/                   # Routes: /, /create, /library, /projects, /generations, /scores, /system
│   ├── components/            # UI primitives, cards, dialogs, project and generation views
│   ├── features/              # Larger screens: the create form, the player, the queue
│   ├── hooks/                 # Data fetching (TanStack Query) and small UI hooks
│   ├── lib/                   # API client, formatting, config path helpers
│   └── store/                 # Zustand stores: player, and which dialog is open
│
├── services/
│   ├── api/                   # FastAPI application (never imports torch)
│   │   └── app/
│   │       ├── api/v1/        # Routes: projects, generations, artifacts, scores, system…
│   │       ├── services/      # Project, generation, budget, capability and system services
│   │       └── core/          # Dependency providers, error envelope, logging
│   ├── yue2_worker/           # GPU worker: claims jobs, runs the model, writes artifacts
│   │   ├── adapters/          # Native YuE2, mock, ComfyUI, and reference transcription
│   │   ├── engine/            # Artifact and manifest writing
│   │   └── model_manager/     # Keeps the checkpoint resident between jobs
│   └── sheetsage2_worker/     # Cover transcription, run as a subprocess in its own venv
│
├── packages/core/             # Shared library used by the API and the worker
│   └── yue2_studio_core/      # Models, store, settings, token budget, ABC, delivery formats
│
├── configs/                   # Parameter registry, defaults, presets, capabilities, model limits
├── docs/                      # Architecture, setup, parameters, API, troubleshooting, licensing
├── scripts/                   # Environment setup, model download, smoke test
├── tests/                     # Unit and integration tests (no GPU needed)
├── tools/ffmpeg/              # Optional private FFmpeg build
├── models/                    # Downloaded weights (not in version control)
├── data/                      # Everything you create (not in version control)
└── Makefile
```

What the important folders mean, in one line each:

- **`apps/web`** — everything you see in the browser.
- **`services/api`** — the HTTP API. It validates requests and queues jobs; it
  never loads a model.
- **`services/yue2_worker`** — the only process that touches the GPU.
- **`packages/core`** — the rules both of them share: what a generation is, where
  it is stored, how many tokens it may use.
- **`configs`** — the single description of every parameter. The API serves it,
  the frontend renders forms from it, the worker validates against it.
- **`data`** — your projects, versions, audio, scores and logs.

---

## Prerequisites

| | |
|---|---|
| OS | Linux. Verified on Ubuntu 22.04. |
| GPU | A BF16-capable NVIDIA card. 24 GB minimum, 48 GB comfortable. |
| Driver | 525 or newer. `nvidia-smi` must work. |
| Python | 3.12 for the worker, 3.11 for the API. `uv` installs them if missing. |
| Node.js | 20 or newer (tested on 22). |
| Disk | About 8 GB for the weights, plus room for the audio you generate. |
| FFmpeg | Optional. Needed for MP3, M4A and OGG downloads; version 6.1+ is additionally required by the cover workflow. `make cover` installs a private build into `tools/ffmpeg`. |

No database and no API keys are required. Nothing is sent anywhere.

Check the GPU before starting:

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
```

---

## Installation

```bash
git clone <repository-url>
cd Music_Studio_YuE2
```

Install `uv` if you do not have it (it builds the two Python environments):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then, with `make`:

```bash
make install          # .venv-api, .venv-yue2 and the frontend dependencies
make models           # ~7.8 GB of weights into ./models
make cover            # optional: FFmpeg 7 + SheetSage2, for covers and conversions
cp .env.example .env  # adjust paths only if your models live elsewhere

make smoke-test       # proves the GPU path works before you open a browser
make dev              # API + worker + frontend together
```

Then open <http://127.0.0.1:3000>.

Without `make`, the same steps are:

```bash
./scripts/setup_api_env.sh      # .venv-api  (FastAPI, no torch)
./scripts/setup_yue2_env.sh     # .venv-yue2 (torch 2.10 cu126 + yue2-infer)
./scripts/setup_cover.sh        # optional
./scripts/download_models.sh
cd apps/web && npm install && cd ../..
cp .env.example .env

./scripts/dev_api.sh --reload                      # terminal 1
./scripts/dev_worker.sh                            # terminal 2
npm --prefix apps/web run dev                      # terminal 3
```

Full instructions, including driver and CUDA specifics:
[docs/setup-linux.md](docs/setup-linux.md).

---

## Environment Variables

Copy `.env.example` to `.env`. Every value has a working default; you normally
only change the model paths. There are no secrets in this file.

```env
APP_ENV=development
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
FRONTEND_URL=http://127.0.0.1:3000
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000

YUE2_MODEL_PATH=./models/YuE2-3B
YUE2_VAE_PATH=./models/YuE2-Vae
YUE2_VAE_LEGACY_PATH=./models/YuE2-Vae-legacy
YUE2_MODEL_REVISION=
YUE2_VAE_REVISION=

DATA_DIR=./data
CONFIGS_DIR=./configs

MAX_CONCURRENT_GPU_JOBS=1
WORKER_ID=local-gpu-0
WORKER_POLL_INTERVAL_SECONDS=0.5
CANCEL_POLL_INTERVAL_SECONDS=0.25
YUE2_BACKEND=native

MODEL_IDLE_UNLOAD_SECONDS=0
YUE2_MEMORY_BUDGET_GIB=40
YUE2_COMPUTE_BACKEND=torch
YUE2_QUANTIZATION=none
YUE2_OFFLOAD_AR=false
YUE2_LOCAL_FILES_ONLY=true

MAX_UPLOAD_BYTES=104857600

SHEETSAGE2_MODEL_PATH=./models/SheetSage2
SHEETSAGE2_VENV=./.venv-sheetsage2
SHEETSAGE2_TIMEOUT_SECONDS=1800
FFMPEG_DIR=./tools/ffmpeg

COMFY_API_URL=
COMFY_WORKFLOW_PATH=./yue2_full.json
```

| Variable | What it does |
|---|---|
| `APP_ENV` | `development` or `production`. Affects logging only. |
| `BACKEND_HOST`, `BACKEND_PORT` | Where the API listens. |
| `FRONTEND_URL` | Allowed CORS origin for the API. |
| `NEXT_PUBLIC_API_BASE_URL` | Where the frontend reaches the API when rendering on the server. |
| `YUE2_MODEL_PATH` | The YuE2-3B directory, or a Hugging Face repo id. |
| `YUE2_VAE_PATH` | The audio decoder directory, or a repo id. |
| `YUE2_VAE_LEGACY_PATH` | Optional older decoder. Its absence disables that option with a reason. |
| `YUE2_MODEL_REVISION`, `YUE2_VAE_REVISION` | Pin a revision for reproducible comparisons. Empty means "whatever is in the directory", which is hashed into every manifest anyway. |
| `DATA_DIR` | Where projects, versions, audio, uploads and presets live. This is the whole database. |
| `CONFIGS_DIR` | Where the parameter registry and defaults are read from. |
| `MAX_CONCURRENT_GPU_JOBS` | How many generations may run at once. 1 on a single card. |
| `WORKER_ID` | Name this worker reports under. Must be unique if you run more than one. |
| `WORKER_POLL_INTERVAL_SECONDS` | How often the worker looks for a new job. |
| `CANCEL_POLL_INTERVAL_SECONDS` | How often a running job checks whether you cancelled it. |
| `YUE2_BACKEND` | `native` (the real model), `mock` (no GPU, used by the tests) or `comfy`. |
| `MODEL_IDLE_UNLOAD_SECONDS` | Seconds of idleness before the 7.26 GB checkpoint is released. `0` keeps it resident. |
| `YUE2_MEMORY_BUDGET_GIB` | Memory budget handed to the pipeline. 24 is the documented baseline; 40 suits a 48 GB card. |
| `YUE2_COMPUTE_BACKEND` | `torch`, `torch-eager` or `vllm`. vLLM is only offered if it is installed. |
| `YUE2_QUANTIZATION` | `none` or `fp8`. FP8 needs compute capability 8.9 or newer. |
| `YUE2_OFFLOAD_AR` | Offload the autoregressive stage to save VRAM, at the cost of speed. |
| `YUE2_LOCAL_FILES_ONLY` | Refuse to reach the network for weights. |
| `MAX_UPLOAD_BYTES` | Largest reference recording accepted for a cover. |
| `SHEETSAGE2_MODEL_PATH`, `SHEETSAGE2_VENV`, `SHEETSAGE2_TIMEOUT_SECONDS` | The cover transcription model, its environment, and how long it may run. |
| `FFMPEG_DIR` | A private FFmpeg build. If it is absent, whatever is on `PATH` is used. |
| `COMFY_API_URL`, `COMFY_WORKFLOW_PATH` | The optional ComfyUI compatibility adapter, off by default. |

`CUDA_VISIBLE_DEVICES` is deliberately **not** read from this file — it is a
driver variable that only has an effect when exported into the worker's shell.
Choose the GPU on the System page instead; see [Choosing a GPU](#choosing-a-gpu).

---

## Complete Application Workflow

```text
Create or open a project
          ↓
Configure the generation  (style, lyrics, mode, duration, seed, advanced settings)
          ↓
Validate  (server side: capabilities, ranges, token budget)
          ↓
Queue the job            → data/jobs/<id>.json
          ↓
Worker claims it         → loads the model on the chosen GPU
          ↓
Transcribe (covers only) → Plan the score → Acoustic tokens → Synthesis → Decode
          ↓
Post-process and write   → audio, score, latents, logs, manifest.json
          ↓
Saved as a new version in the project's history
          ↓
Play · Regenerate · Rename · Download · Delete
```

Nothing in that chain is faked. If a stage cannot report real progress, it
reports counts instead of a percentage. If a run is cut short, it ends as
`INCOMPLETE` rather than `COMPLETED`.

---

## How to Generate Audio

### Step 1 — Create or select a project

Press **Create** in the sidebar to start a new song, or open **Projects** and
choose **New version** inside an existing one. A project is created
automatically the first time you generate from scratch.

### Step 2 — Configure the generation

Describe the **style**: genre, instruments, vocal character, language and tempo.
This is the single most important field. The examples under the box are a
starting point you can click.

### Step 3 — Add the lyrics

Write the lyrics with section tags on their own lines — `[Verse]`, `[Chorus]`,
`[Bridge]`. The buttons above the box insert them. Choose **Direct Audio** if you
want an instrumental and no lyrics at all.

### Step 4 — Choose the mode

- **Full Song** — the model writes a score, then performs it.
- **Melody Guided** — a lighter plan, closer to your phrasing.
- **Direct Audio** — no score, no lyrics.
- **Score Edit** — you supply the ABC score.
- **Cover** — upload a recording; it is transcribed and re-performed in your style.

### Step 5 — Adjust the settings

Set the **maximum duration** and the **seed**. Open **Advanced settings** for
everything else: sampling temperature, guidance scale, ODE steps, decoder tiling,
output format, the model checkpoint. Hover or tap the ⓘ beside any control for
what it does, what happens if you raise or lower it, and what it costs.

Watch the **token budget** panel as you go. It counts the real context with the
checkpoint's own tokenizer and tells you whether the song fits before you spend
any GPU time.

### Step 6 — Start the generation

Press **Create** (or **Generate new version**). The job is validated on the
server, queued, and you are taken to its page.

### Step 7 — Watch it run

The generation page streams the real stage: loading the model, planning,
generating tokens, decoding, writing files. You can cancel at any point, and the
run stops at the next checkpoint rather than being killed.

### Step 8 — Listen

When it finishes, the waveform appears and the player bar follows you around the
app. The score, the manifest and the full log are on the same page.

### Step 9 — Regenerate or make another version

Press **Regenerate** to open the same settings in an editable form, change
anything, and generate a new version alongside the old one.

---

## Project and Generation Workflow

```text
Create project
       ↓
Generate version 1
       ↓
Saved to the project's history
       ↓
Select any earlier version
       ↓
Regenerate
       ↓
That version's complete configuration is restored, and editable
       ↓
Change any parameter
       ↓
Generate version 2
       ↓
Both versions remain available
```

The rules behind this, which the code enforces and the tests check:

- **Earlier versions are preserved.** Regenerating never writes to the version
  it started from.
- **Regeneration creates a new version.** It gets a new id, a new number, and
  records which version it came from.
- **Each version stores its own configuration snapshot.** It is written when the
  job is created and never rewritten — not by editing the project, not by
  changing the defaults, not by regenerating.
- **Versions can be deleted individually.** Deleting version 2 leaves 1 and 3
  exactly as they were, and version 2's number is never handed out again.
- **The project itself can be renamed, reconfigured or deleted.** Editing a
  project's configuration changes where its *next* version starts from, and
  nothing else.
- **Deleting a project deletes its whole history**, after a confirmation that
  says how many versions that is. A project with a generation still running
  cannot be deleted; cancel it first.

---

## Audio Download Workflow

```text
Select a version
       ↓
Click Download
       ↓
Choose a format   (only the ones this machine can actually write)
       ↓
Type a file name  (the extension is added for you)
       ↓
Download
```

**Supported formats.** FLAC, WAV, MP3, M4A (AAC) and OGG Vorbis. Which of them
appear is decided by asking the installed FFmpeg which encoders it has, so a
format is never offered that would then fail. Without FFmpeg, only the master's
own format is offered, and the rest are listed with the reason they are not.

**The original is never modified.** The model's output is the master. Choosing
its own format hands that file over byte for byte. Choosing another converts a
copy into a temporary directory, serves it, and deletes it as soon as the
download finishes — abandoned files are swept after fifteen minutes.

**Filenames.** Whatever you type is sanitised on the server: directory
separators, control characters and reserved names are removed, so a filename
cannot point anywhere but at its own download. The extension is appended, and an
extension you typed yourself is not repeated — `song.mp3` stays `song.mp3`
rather than becoming `song.mp3.mp3`. An empty name falls back to
`YuE2-<title>-v<version>`.

**Conversion failures are reported**, never hidden behind a truncated file. A
conversion that fails or times out deletes its partial output and returns the
error FFmpeg gave.

---

## How it is put together

```text
apps/web ──REST + SSE──> services/api ──job document──> data/jobs/
   Next.js                  FastAPI                          │
                                                             ▼
                                             services/yue2_worker  (own venv)
                                                  ModelManager
                                                  Native YuE2 adapter
                                                       │
                                                       ▼
                                          data/projects/<id>/generations/<id>/
                                             audio/ score/ intermediates/ logs/
                                             manifest.json
```

Three processes, one shared directory. The API never imports torch; the worker
never serves HTTP. The queue is a directory of JSON documents guarded by an
advisory lock, behind a `JobQueue` interface that Redis, Celery or Dramatiq can
implement later without touching a caller.

Read [docs/architecture.md](docs/architecture.md) for the full picture.

### Where your work is stored

```text
data/
  projects/<project-id>/project.json              # name, settings, which version is current
  projects/<project-id>/generations/<id>/
      request.json          # what you asked for
      effective_config.json # what actually ran
      manifest.json         # weights, runtime, timings, hashes
      job.json              # status, progress, budget, lineage
      audio/ score/ intermediates/ logs/
  jobs/<generation-id>.json                       # the queue
  uploads/<upload-id>/                            # cover reference recordings
  presets/<preset-id>.json
  runtime-settings.json                           # the GPU you picked
```

Every write is atomic — a temporary file plus a rename — so a crash never leaves
a half-written record. A generation folder is self-describing: copy it somewhere
else and it still says what produced it.

---

## The rules this project is built around

**1. Parameters are defined once.** `configs/parameter-registry.json` describes
every setting — its range, its help text, its native equivalent and its ComfyUI
origin. The API serves it at `/api/v1/generation/schema`, the frontend renders
forms from it, the worker validates against it, and `configs/workflow-mapping.json`
is generated from it. No parameter is described twice.

**2. Nothing is silently dropped or substituted.** The ComfyUI workflow exposes
`sampler_name`, `scheduler`, `denoise`, `seconds` and `batch_size`. The native
runtime has no equivalent for any of them. Setting one is refused with the
reason, and the UI shows the control disabled with that reason attached — it is
never accepted and then ignored.

**3. A fragment is never sold as a song.** The model decides how long a song is;
the duration setting is a hard stop, not a target. The studio counts context with
the checkpoint's own tokenizer, reads the written score's own length before any
audio is generated, and then either raises the limit so the song can finish —
reporting the change — or refuses before spending the GPU time. A run that does
get cut off ends as `INCOMPLETE`, never `COMPLETED`. See
[docs/parameter-guide.md](docs/parameter-guide.md#how-duration-really-works).

**4. Progress is never invented.** Token stages report real counts and a rate,
with no percentage, because a generation limit is a ceiling and not a target.
Stages that do have a target — ODE solver steps, decoder chunks, transcription
windows — report a real percentage.

**5. Every setting explains itself.** All 48 parameters carry plain-language help
served by the backend: what it is, what happens if you raise or lower it, what is
recommended, what an extreme value does, and whether it costs time or memory. It
appears behind an ⓘ beside the label — or a ⚠ for the seventeen settings where an
unusual value genuinely destabilises output, inflates VRAM or lengthens a run.
Hover on a desktop, tap on a phone, or reach it with the keyboard. See
[docs/parameter-guide.md](docs/parameter-guide.md).

**6. History is immutable.** A generation's configuration is written when it is
queued and never rewritten. Editing a project, changing the defaults or
regenerating all leave every earlier version exactly as it was.

---

## Choosing a GPU

On a machine with more than one card, or one shared with other work, the System
page lists every GPU with its free memory, its utilisation and how much other
processes are holding, and lets you pick which one loads the model. The choice is
stored in `data/runtime-settings.json` and applies to the next generation; a run
already in flight finishes on the card it started on.

`CUDA_VISIBLE_DEVICES` in `.env` does **not** control this, and never did — that
file is read into the application's settings, not exported into the worker's
process environment. Use the System page, or export the variable in the shell
that starts the worker if you want to hide cards entirely.

---

## Reproducibility

Every completed generation writes `manifest.json` containing the request as
submitted, the effective configuration, per-file SHA-256 of the model and decoder
weights, the runtime versions, the GPU, the timings and the peak VRAM. The seed
that was actually used is always recorded, including when the studio drew it.

```jsonc
{
  "schema_version": 1,
  "weights": { "mot": { "files": { "model.safetensors": { "sha256": "1d55c42c…" } } } },
  "runtime":  { "torch": "2.10.0+cu126", "yue2-infer": "0.1.6", "latent_frame_rate": 25 },
  "timing":   { "planning_seconds": 10.9, "decode_seconds": 3.0, "gpu_peak_bytes": 7777752064 }
}
```

---

## Upgrading an existing installation

There is no database, so there is no schema migration. Two fields were added to
the JSON records — `version` and `parent_generation_id` on a generation,
`default_config` and `generation_counter` on a project — and every one of them
has a default, so records written by an earlier version load unchanged and
nothing needs converting.

The one cosmetic gap: generations created before versions existed all load as
version 1, so a project that already held several of them shows several
"version 1"s. One command fixes that, and it only ever writes those numbers:

```bash
make backfill-versions            # report what it would change
make backfill-versions APPLY=1    # write it
```

It is safe to run more than once, and a project whose numbers are already
distinct is left alone.

## Testing

```bash
make test             # everything that does not need a GPU
make test-unit        # unit tests
make test-integration # API, queue and worker against the mock backend
make lint             # TypeScript types, ESLint, Python syntax
make smoke-test       # a real generation on the GPU
```

---

## Troubleshooting

**The worker is offline / the health badge says so.** The API runs without the
worker, but nothing will generate. Start it with `make worker` and check
`logs/` for the reason it stopped.

**"The model 'x' cannot be loaded".** The checkpoint directory is missing or
incomplete. Run `make models`, or point `YUE2_MODEL_PATH` at where the weights
actually are. The System page names the exact path it looked in.

**CUDA out of memory.** Your settings are never changed behind your back, so the
run fails rather than quietly shrinking. Lower the maximum duration, use the
tiled decoder with a smaller tile, enable AR offload, or lower
`YUE2_MEMORY_BUDGET_GIB`. If another process is holding the card, pick a
different GPU on the System page.

**"The request does not fit in the model's context window."** The song you asked
for needs more tokens than remain after the style, lyrics and score. The message
gives the numbers and the longest duration that would fit. Shorten the duration
or the lyrics.

**A version came out `INCOMPLETE`.** The model was still singing when the
duration limit ran out, so what you have is part of a song. It is kept and
playable, a short fade is applied so the cut does not click, and the page offers
to retry with a longer limit. It is deliberately not counted as completed.

**Cover mode is disabled.** It needs SheetSage2, its own Python environment and
FFmpeg 6.1 or newer. Run `make cover`. The System page says which of the three is
missing.

**A download format is missing from the dialog.** The installed FFmpeg has no
encoder for it. The dialog lists the unavailable formats and the reason under
"formats unavailable on this machine". `make cover` installs a build that
supports all five.

**FFmpeg is not installed.** Only the master's own format can be downloaded, and
MP3 delivery at generation time is disabled with that reason. Everything else
works.

**A project will not delete.** A generation in it is still queued or running.
Cancel it, then delete the project.

**The page stops responding to clicks after a dialog closes.** This was a real
bug and is fixed; if you ever see it again, it is worth reporting. Every shared
dialog is now mounted once at the top of the tree rather than inside the card it
belongs to, precisely so that closing one cannot leave the page locked.

More, including the full error taxonomy:
[docs/troubleshooting.md](docs/troubleshooting.md).

---

## Documentation

| | |
|---|---|
| [architecture.md](docs/architecture.md) | Modules, data flow, storage layout, worker lifecycle |
| [setup-linux.md](docs/setup-linux.md) | Exact commands for Linux + NVIDIA |
| [model-setup.md](docs/model-setup.md) | Weights, revisions, verification |
| [parameter-guide.md](docs/parameter-guide.md) | Every control in plain language |
| [api.md](docs/api.md) | HTTP and streaming contract |
| [cover-workflow.md](docs/cover-workflow.md) | SheetSage2 and the cover path |
| [score-editing.md](docs/score-editing.md) | ABC editing and regeneration |
| [troubleshooting.md](docs/troubleshooting.md) | Error codes and what to do |
| [licensing.md](docs/licensing.md) | Weights are CC BY-NC 4.0 |

---

## Licensing, briefly

The YuE2 checkpoint weights are **CC BY-NC 4.0** — non-commercial. That covers the
weights and what you do with their output; it is separate from this application's
source. The YuE2 runtime and the vendored ABC parser are Apache-2.0. Details in
[docs/licensing.md](docs/licensing.md) and on the in-app About page.

---

## Author

**Farzine**
