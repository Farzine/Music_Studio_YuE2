# YuE2 Music Studio — Visual Guide

Follow the desktop screenshots from setup to a finished song. Click an image to enlarge it; expand the optional examples for individual dialogs.

[Setup](#setup) · [Hardware](#hardware) · [Download](#download) · [Models](#models) · [Create](#create) · [Listen](#listen) · [Library](#library) · [Scores](#scores) · [Settings](#settings) · [Demo](#demo) · [Help](#help) · [Developer reference](#development)

## Workflow

![Download, validate, select resources, generate and export](docs/assets/workflow.png)

## Setup

**Requirements:** Linux, an NVIDIA CUDA GPU, working `nvidia-smi`, Git, `uv`, Python 3.11 for the API and Node.js 20+ (tested on 22). The worker setup installs Python 3.12 if needed. GGUF additionally needs the CUDA toolkit (`nvcc`), CMake and a C++ compiler. Allow space for weights, download staging and generated audio.

Run from the repository root:

```bash
git clone https://github.com/Farzine/Music_Studio_YuE2.git
cd Music_Studio_YuE2
make install              # Creates .env if absent; installs API, worker and web
make install-audiocpp     # Required for GGUF inference
make dev
```

Open **http://127.0.0.1:3000**. The API runs on port **8000**. Download a GGUF package through the studio using the steps below. For native YuE2 weights and VAE, run `make models` instead of downloading a GGUF package.

Settings live in [.env.example](.env.example); edit your local `.env` for model paths, storage and memory budget. Restart processes after changing that file. GPU selection through **System** takes effect dynamically.

<details>
<summary>Run services separately, optional covers and shutdown</summary>

Use three terminals:

```bash
./scripts/dev_api.sh --reload
./scripts/dev_worker.sh
npm --prefix apps/web run dev
```

For native Cover mode, run `make cover` to install SheetSage2, its weights and private FFmpeg. The UI explains when a mode is unavailable for the chosen backend.

Stop `make dev` with **Ctrl+C** and let cleanup finish. The worker settles active work and releases models, VAE and child processes. Hard OS termination cannot run Python cleanup.

</details>

## Hardware

Open **System**. Check that the worker is online, inspect free VRAM and select a GPU. Wait for the switch result before submitting work. Model Capacity reserves memory for runtime overhead and the VAE; estimates are not guarantees.

![System: GPU selection, model capacity, worker status and storage](docs/assets/screenshots/system-desktop.png)

<details>
<summary>Compare recommended models</summary>

Open **Models → Recommended Models**, choose the GPU to evaluate and read each model's reasons. Evaluating a GPU does not switch the worker or download a model.

![Recommended models and compatibility estimates](docs/assets/screenshots/recommendations-desktop.png)

</details>

## Download

Open **Models → Download Model**:

1. Enter a repository, such as `audio-cpp/Yue2-3B-GGUF`, and a branch, tag or commit. Click **Inspect Repository**.
2. Choose a primary weight, such as `yue2-3b-q4_0.gguf`. Include recognized companion files; this runtime needs its bundled F16 VAE and sidecars.
3. Preview the download. Review size, free disk space and compatibility, then click **Start Download**.

![Inspected repository, revision and selectable model files](docs/assets/screenshots/repository-inspection-desktop.png)

<details>
<summary>Download page and preview</summary>

Download content can be a model package, selected files or the repository. Inspection pins the revision to an exact commit.

![Download page](docs/assets/screenshots/download-desktop.png)

Progress uses transferred bytes: **Queued → Downloading → Verifying → Registering → Completed**. Failed jobs offer retry and partial-file cleanup. Completion records the download; current inference readiness appears separately.

![Download preview with storage and compatibility checks](docs/assets/screenshots/download-preview-desktop.png)

</details>

## Models

Open **Installed Models**. Check the readiness badges, then choose **Use Model** to open Create with that checkpoint. **Inference ready** means runtime prerequisites passed; **Not loaded** simply means the worker is not holding it in GPU memory.

![Installed models and VAEs with use, inspect, load, unload and delete actions](docs/assets/screenshots/models-desktop.png)

<details>
<summary>Inspect, repair missing files or remove an installation</summary>

**Inspect** shows source, revision, format, validation and local paths.

![Model inspection](docs/assets/screenshots/model-inspection-desktop.png)

**Repair installation** checks the original pinned repository, reuses healthy files and downloads missing or damaged content. Review the preview before **Repair and validate**. Repair requires recorded Hugging Face provenance and managed storage.

![Repair preview](docs/assets/screenshots/model-repair-desktop.png)

**Delete** shows the exact installation and disk space to reclaim. Missing registered installations can also be removed. Active tasks and loaded models block deletion; finish the task and unload first.

![Model deletion confirmation](docs/assets/screenshots/model-delete-confirmation-desktop.png)

</details>

Native models support persistent **Load / Unload**. GGUF weights load per generation through audio.cpp; select them in Create even when persistent Load is disabled.

## Create

Choose **Model**, **VAE** and **GPU** independently. For GGUF, choose the package's **Bundled YuE2 F16 VAE**. Enter a title, musical style and section-tagged lyrics, choose **Full Song**, review the budget and generate.

**Maximum duration is a ceiling**, not an exact song length. Start with a short song and enough headroom for the ending. The screenshot shows regeneration: submitting creates a new version while preserving the original.

![Create: independent resources, style, lyrics, mode and duration](docs/assets/screenshots/create-desktop.png)

<details>
<summary>Advanced settings and presets</summary>

Expand a settings group to adjust planning, sampling, synthesis or output. Unavailable controls explain backend restrictions. Presets preserve explicit task resource choices.

![Advanced generation settings](docs/assets/screenshots/advanced-settings-desktop.png)

Use **Save as preset** to reuse settings later.

![Save preset dialog](docs/assets/screenshots/save-preset-desktop.png)

</details>

## Listen

Follow the generation's stage updates. When complete, play the waveform, inspect the saved settings and choose **Download…**.

![Completed generation with audio and recorded configuration](docs/assets/screenshots/generation-desktop.png)

<details>
<summary>Playback, export and an incomplete result</summary>

The player supports seeking and keeps playing while you navigate.

![Audio player](docs/assets/screenshots/audio-player-desktop.png)

Choose a format and filename. Conversion leaves the original audio intact; available formats depend on installed FFmpeg encoders.

![Audio export dialog](docs/assets/screenshots/audio-download-desktop.png)

**INCOMPLETE** means the model reached a limit before finishing. The fragment is retained. Regenerate with a larger duration/token allowance where the context budget permits.

![Incomplete generation with its recorded limit](docs/assets/screenshots/generation-incomplete-desktop.png)

</details>

## Library

Use **Library** to search, filter, play and download generations. **Projects** groups versions of a song; changing project settings affects future versions.

![Audio library](docs/assets/screenshots/library-desktop.png)

<details>
<summary>Dashboard, projects, version settings and deletion</summary>

The dashboard links to recent work and Create.

![Dashboard](docs/assets/screenshots/dashboard-desktop.png)

Open a project to continue a song.

![Projects list](docs/assets/screenshots/projects-desktop.png)

Compare versions or start a new one from project history.

![Project version history](docs/assets/screenshots/project-desktop.png)

Save resource and generation defaults in project configuration.

![Project configuration](docs/assets/screenshots/project-settings-desktop.png)

Generation deletion names the version and its artifacts. Cancel preserves it; running work must settle before deletion.

![Generation deletion confirmation](docs/assets/screenshots/generation-delete-confirmation-desktop.png)

</details>

## Scores

Open a generation's **Score** to edit its ABC, **Validate**, then save and regenerate. A new generation preserves the earlier take. Direct Audio may have no score.

![ABC score editor](docs/assets/screenshots/score-desktop.png)

<details>
<summary>Validation, comparison and the scores library</summary>

Validate before regeneration; a syntactically valid edit can still change the musical interpretation.

![Score validation](docs/assets/screenshots/score-validation-desktop.png)

Compare the draft with the source before saving.

![Score comparison](docs/assets/screenshots/score-comparison-desktop.png)

The Library's **Scores** tab filters to versions with a score artifact.

![Scores library](docs/assets/screenshots/library-scores-desktop.png)

</details>

## Settings

Use **Settings** to review paths and presets. To register existing weights, select file or folder mode, browse, validate the selected path and register it. Paths refer to the API host.

![Settings and local model registration](docs/assets/screenshots/settings-desktop.png)

<details>
<summary>File browser and About</summary>

**Browse File** opens allowed model roots. Changing a path requires fresh validation.

![Host file browser](docs/assets/screenshots/file-browser-desktop.png)

**About** lists application, model and runtime information and attribution.

![About page](docs/assets/screenshots/about-desktop.png)

</details>

## Demo

**City Lights, Open Sky** — [Listen to MP3](docs/demo/city-lights-open-sky.mp3) · [Lossless FLAC](docs/demo/city-lights-open-sky.flac)

<audio controls preload="metadata" aria-label="Play City Lights, Open Sky" src="docs/demo/city-lights-open-sky.mp3">
  <a href="docs/demo/city-lights-open-sky.mp3">Download the MP3</a>
</audio>

If your Markdown viewer hides the controls, open [docs/demo/index.html](docs/demo/index.html) locally in your browser.

A real **65.76-second**, stereo 48 kHz generation made on an RTX A6000 using audio.cpp v0.8.2, YuE2 Q4_0 and the bundled F16 VAE. Completed on 4 October 2026 with no generation warnings.

To try it: select your installed Q4 package and VAE, paste the [style](docs/demo/style.txt) and [lyrics](docs/demo/lyrics.txt), choose Full Song, seed **20261004**, a **90-second** maximum and **2,048** planning tokens. Automatic fit-to-plan was disabled for this demo.

[Configuration](docs/demo/config.json) · [ABC score](docs/demo/score.abc) · [Measured report and checksum](docs/demo/report.json)

The configuration contains this machine's paths; select your own installation. Hardware/runtime differences can change results even with the same seed.

## Help

| What you see | What to do |
|---|---|
| audio.cpp CLI is not installed | Run `make install-audiocpp`. If CUDA is elsewhere, use `CUDACXX=/path/to/nvcc make install-audiocpp`. |
| Downloaded model cannot be selected | Inspect its readiness reason; verify runtime, required companions and compatible VAE. |
| Missing or damaged files | Use **Repair installation**; retry a failed download from its job. |
| Missing installation you no longer want | Use its confirmed **Delete / Remove missing installation** action. |
| Worker offline / jobs stay queued | Run `./scripts/dev_worker.sh`; inspect its log and wait for a fresh heartbeat on System. |
| GPU memory exhausted | Pick a smaller compatible model, reduce memory demand or use another GPU; inspect free VRAM. |
| GPU switch or unload failed | Read the worker command error; wait for active work and cleanup. Do not assume the switch succeeded. |
| Song ends early | Inspect **INCOMPLETE** details and raise the duration allowance if the context budget permits. |
| MP3 or another format unavailable | Install/configure FFmpeg with the required encoder; download the original meanwhile. |
| Cover unavailable | Install `make cover` and choose a backend that supports transcription. |

## Development

| Location | Responsibility |
|---|---|
| `apps/web/` | Next.js UI, forms and displayed API/worker state |
| `services/api/` | FastAPI, validated settings, downloads and persistent records |
| `services/yue2_worker/` | GPU loading, inference, device switching and cleanup |
| `packages/core/` | Shared model metadata, registry, validation and compatibility rules |
| `configs/` | Parameter schema, defaults and presets |
| `models/`, `data/` | Local weights and user projects; preserve during cleanup |

API operations and schemas are available at **http://127.0.0.1:8000/docs** while running. The API never loads CUDA models. Extend shared compatibility metadata and worker adapters together when adding a backend; the frontend displays their results.

```bash
make test
make lint
npm --prefix apps/web run test
npm --prefix apps/web run test:browser
npm --prefix apps/web run build
```

Browser tests still cover desktop and mobile layouts; documentation screenshots use desktop only. Tests use mock backends unless explicitly running `make smoke-test`, which performs real GPU generation. Physical native/vLLM multi-GPU rollback remains unverified by the recorded demo.

To refresh screenshots against a running studio, supply actual IDs:

```bash
cd apps/web
node scripts/capture-docs.cjs GENERATION_ID PROJECT_ID
```

The script uses installed Chrome by default (`PLAYWRIGHT_CHANNEL` overrides it). It opens dialogs but does not confirm deletions or submit generations. [Capture manifest](docs/assets/screenshots/manifest.json) records the real routes. [Workflow SVG](docs/assets/workflow.svg) is the editable source for the diagram.

## Licensing

YuE2 model weights are **CC BY-NC 4.0**; retain their license and attribution files. The YuE2 runtime and vendored ABC parser carry Apache-2.0 notices. Application source and dependency licenses are separate. Model licenses remain authoritative for permitted use.
