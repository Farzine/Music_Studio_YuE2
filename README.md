# YuE2 Music Studio — Visual Guide

Follow the desktop screenshots from setup to a finished song. Click an image to enlarge it; expand the optional examples for individual dialogs.

[Setup](#setup) · [Hardware](#hardware) · [Download](#download) · [Models](#models) · [Create](#create) · [Listen](#listen) · [Library](#library) · [Scores](#scores) · [Settings](#settings) · [▶ Play demo](#demo) · [Help](#help) · [Developer reference](#development)

**Featured demo:** [Mehedi Rifat song — play and view lyrics, style & settings](#demo) · 6:05.88 · native YuE2 BF16

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

Open **http://127.0.0.1:3000**. The API runs on port **8080**. Download a GGUF package through the studio using the steps below. For native YuE2 weights and VAE, run `make models` instead of downloading a GGUF package.

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

### Mehedi Rifat song

**6:05.88 · Bengali storytelling · 48 kHz stereo · Native YuE2 BF16**

A completed song from the requested project, generated on **5 October 2026**. Warm male vocals, acoustic guitar and light piano; the exact lyrics and style used are available below.

<audio controls preload="metadata" aria-label="Play Mehedi Rifat song" src="docs/demo/mehedi-rifat.mp3">
  <a href="docs/demo/mehedi-rifat.mp3">Listen / download MP3</a>
</audio>

**[Open demo player](docs/demo/index.html)** · [MP3](docs/demo/mehedi-rifat.mp3) · [Original prj_0muuvzvo6bau2ngwb/generations/gen_0muv0by7ibi0dr1nf/audio/final.flac](docs/demo/prj_0muuvzvo6bau2ngwb/generations/gen_0muv0by7ibi0dr1nf/audio/final.flac)

If your Markdown viewer hides audio controls, open `docs/demo/index.html` locally in a browser. Click below to reveal the full song details directly in this README.

<details>
<summary><strong>View lyrics, style &amp; generation settings</strong></summary>

#### Style prompt

```text
Gentle Bengali storytelling song with warm male vocals. Sing slowly and clearly at around 75–80 BPM, with accurate standard Bangladeshi Bengali pronunciation. No rap, no rushing, no slurred words. Use natural pauses between lines and give longer lyrics extra time instead of speeding up.
Keep the music soft and simple: acoustic guitar, light piano, bass, and gentle drums. Verses should feel conversational and humorous, chorus slightly fuller but still controlled. Pronounce Bengali and Bengali-written English words clearly. Prioritize diction, clarity, and storytelling over speed or vocal tricks.
```

#### Lyrics

```text
[Intro]
দুনিয়ায় কিছু মানুষ আসে ইতিহাস গড়তে,
কেউ আসে পৃথিবী বদলাতে, কেউ আসে স্বপ্ন ধরতে।
আর কিছু মানুষ আসে
চায়ের দোকানে বসে পৃথিবী কীভাবে বদলানো উচিত, সেটা বলতে।
আজকের গল্প দুই মহাপুরুষের।
লেডিস অ্যান্ড জেন্টলম্যান...
মিট মেহেদী and রিফাত।
একজন কাজ শুরুর আগেই বলে “হবে না ভাই।”
আরেকজন কাজ শুরু না করেই বলে
“ভাই, বিলিয়ন ডলারের আইডিয়া!”
[Verse]
সকালবেলা মেহেদী ওঠে, মুখে শোকের ছায়া,
দিনটা শুরুই হয়নি; শেষ হয়ে গেছে মায়া।
বললাম, “ভাই, একটা project ট্রাই করে দেখি?”
মেহেদী বলে, “লাভ নাই ভাই, সামনে বিপদ দেখি।”
আইডিয়া বললে রিস্ক দেখে, প্ল্যান বললেই লস,
সুযোগ দরজায় আসলে বলে “হবে না বস!”
ইন্টারভিউয়ের আগেই ভাবে রিজেকশন আসবে,
চেষ্টা করার আগেই প্রজেক্ট আন্ডারগ্রাউন্ড,
মেহেদীর নেগেটিভিটি ডলবি সারাউন্ড!
মেহেদী, তুমি পেসিমিস্ট না ভাই...
তুমি ফেইলিউরের অ্যাডভান্স বুকিং সিস্টেম।
[Verse]
এবার আসেন রিফাত ভাই, ভিশনারি ম্যান,
প্রতি শুক্রবার স্টার্টআপ, প্রতি শনিবার প্ল্যান।
রবিবার ভ্যালুয়েশন হান্ড্রেড মিলিয়ন,
সোমবার সকাল আসলেই, সিইও সাহেব লস্ট!
রোডম্যাপ আছে, হোয়াইটবোর্ডে চার্ট,
পিচ ডেক রেডি; প্রজেক্ট হয়নি স্টার্ট।
মনে মনে ফাউন্ডার অ্যান্ড সিইও,
কোম্পানি নাই, প্রোডাক্ট নাই, এমপ্লয়ি জিরো।
রাত তিনটায় ওয়ার্ল্ড ডমিনেশন কল,
পরদিন বলি, “কাজ কই?”
—“ভাই... ভাবতেছি ওভারঅল।”
[Pre-Chorus]
একজন—“হবে না ভাই!”
আরেকজন—“হবে... কিন্তু আজকে না!”
একজন অ্যাকশনের আগে ডিপ্রেশন,
আরেকজন অ্যাকশন ছাড়াই প্রেজেন্টেশন!
[Chorus]
সো, ফাক ইউ মেহেদী!
অ্যান্ড ফাক ইউ রিফাত!
একজন ওয়াকিং ডিপ্রেশন,
আরেকজন পাওয়ারপয়েন্টের সম্রাট!
ফাক ইউ মেহেদী!
and ফাক ইউ রিফাত!
[Verse]
একদিন দুজন বলল, “ভাই, বিজনেস করা যাক!”
আমি ভাবলাম; মিরাকল দেখা যাক!
রিফাত বলে—
“আচ্ছা... আগে লোগো বানাই।”
ছয় ঘণ্টা লোগো মিটিং হলো ভাই,
কোম্পানির নাম পনেরোটা—প্রোডাক্ট একটাও নাই!
[Bridge]
কখনো ভাবি, বেশি রোস্ট করছি নাকি?
মেহেদী মেসেজ দেয়—
“ভাই, মনে হয় আমাদের কিছু হবে না।”
রিফাত মেসেজ দেয়—
“ব্রো, নতুন একটা আইডিয়া আসছে। হিউজ পোটেনশিয়াল।”
আমি বলি—“আগেরটা?”
সিন।
নো রিপ্লাই।
[Chorus]
ফাক ইউ মেহেদী!
ফাক ইউ রিফাত!
একজন ট্র্যাজেডি আগে লেখে,
আরেকজন স্টার্টআপ বানায় মিডনাইট চ্যাট!
মেহেদীর কাছে হোপ গেলে
হোপই ডিপ্রেশন নিয়ে ফেরে!
রিফাতের কাছে কাজ দিলে
ডেডলাইন আত্মগোপন করে!
তোমরা দুইজন বন্ধু না—
প্রোডাক্টিভিটির কো-অর্ডিনেটেড অ্যাটাক!
[Outro]
তবুও তোরা আমার ভাই,
এই কারণেই এত কথা।
মেহেদী—
একদিন অন্তত কাজ শুরু করার পরে হতাশ হইস।
রিফাত—
আইডিয়া বলার আগে অন্তত একটা ফোল্ডার বানাইস।
একজন একটু অপটিমিস্টিক হ।
আরেকজন... বিছানা থেকে ওঠ।
[দুই সেকেন্ড নীরবতা]
রিফাত:
“ভাই... নতুন একটা স্টার্টআপ আইডিয়া আছে—”
ন্যারেটর:
“চুপ কর, বাল।”
[গিটার: টুং...]
[END]
```

#### Generation settings

| Setting | Recorded value |
|---|---|
| Version | 6 · Completed |
| Audio | 6:05.88 · stereo · 48 kHz |
| Model | YuE2-3B · native PyTorch · BF16 |
| VAE | Standard YuE2 VAE · FP32 |
| Device | cuda:0 |
| Mode | Full Song |
| Seed | 831001 |
| Duration ceiling | 600 seconds · fit to plan enabled |
| Planning | Temperature 0.7 · top-p 0.9 · top-k 30 · max 4,096 tokens |
| Audio sampling | Temperature 1.0 · top-p 0.95 · top-k 100 · max 15,000 tokens |
| Synthesis | 32 ODE steps · midpoint · effective CFG 1.0 |
| Decoder | Tiled · 1,024 core frames · 16 halo frames |
| Memory budget | 40 GiB · AR offload disabled |
| Measured generation time | 195.005 seconds |
| Recorded finish | 2026-10-05T08:51:24.214972+00:00 |

<details>
<summary>All requested settings</summary>

```json
{
  "model": {
    "checkpoint": "/mnt/lab/farzine/Music_Studio_YuE2/models/YuE2-3B",
    "revision": null,
    "vae": "standard",
    "vae_revision": null,
    "device_index": 0,
    "compute_backend": "torch",
    "quantization": "none",
    "offload_ar": false,
    "memory_budget_gib": 40.0,
    "local_files_only": true
  },
  "planner": {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 30,
    "repetition_penalty": 1.005,
    "penalty_window": 100,
    "min_tokens": 32,
    "max_tokens": 4096,
    "seed": null
  },
  "sampling": {
    "temperature": 1.0,
    "top_p": 0.95,
    "top_k": 100,
    "repetition_penalty": 1.2,
    "penalty_window": 50,
    "min_tokens": 200,
    "max_tokens": 15000,
    "seed": 831001,
    "control_after_generate": "fixed",
    "max_duration_seconds": 600.0,
    "max_tokens_override": null,
    "fit_to_plan": true
  },
  "synthesis": {
    "cfg_scale": null,
    "ode_steps": 32,
    "ode_method": "midpoint",
    "sampler_name": null,
    "scheduler": null,
    "denoise": null,
    "seconds": null,
    "batch_size": null
  },
  "decoder": {
    "mode": "tiled",
    "tile_frames": 1024,
    "halo_frames": 16
  },
  "output": {
    "format": "flac",
    "fade_out_incomplete_ms": 250,
    "filename_prefix": "YuE2",
    "keep_canonical": true
  },
  "mode": "full"
}
```

</details>

These are the completed generation's saved inputs, not the project's editable defaults. The model finished after **365.88 seconds** within a 600-second ceiling. Select your own installed model paths before reusing the configuration.

[Request JSON](docs/demo/prj_0muuvzvo6bau2ngwb/generations/gen_0muv0by7ibi0dr1nf/request.json) · [Effective runtime settings](docs/demo/prj_0muuvzvo6bau2ngwb/generations/gen_0muv0by7ibi0dr1nf/effective_config.json) · [Generation manifest](docs/demo/prj_0muuvzvo6bau2ngwb/generations/gen_0muv0by7ibi0dr1nf/manifest.json) · [ABC score](docs/demo/prj_0muuvzvo6bau2ngwb/generations/gen_0muv0by7ibi0dr1nf/score/source.abc) · [Copied project record](docs/demo/prj_0muuvzvo6bau2ngwb/project.json)

The complete source project is copied under `docs/demo/prj_0muuvzvo6bau2ngwb/`, including its available generation, original audio and intermediate artifacts. The MP3 is a convenience export; the original project under `data/` is unchanged.

</details>

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

API operations and schemas are available at **http://127.0.0.1:8045/docs** while running. The API never loads CUDA models. Extend shared compatibility metadata and worker adapters together when adding a backend; the frontend displays their results.

```bash
make test
make lint
npm --prefix apps/web run test
npm --prefix apps/web run test:browser
npm --prefix apps/web run build
```

Browser tests still cover desktop and mobile layouts; documentation screenshots use desktop only. Tests use mock backends unless explicitly running `make smoke-test`, which performs real GPU generation. The demo verifies a native generation on CUDA device 0; multi-GPU rollback remains unverified.

To refresh screenshots against a running studio, supply actual IDs:

```bash
cd apps/web
node scripts/capture-docs.cjs GENERATION_ID PROJECT_ID
```

The script uses installed Chrome by default (`PLAYWRIGHT_CHANNEL` overrides it). It opens dialogs but does not confirm deletions or submit generations. [Capture manifest](docs/assets/screenshots/manifest.json) records the real routes. [Workflow SVG](docs/assets/workflow.svg) is the editable source for the diagram.

## Licensing

YuE2 model weights are **CC BY-NC 4.0**; retain their license and attribution files. The YuE2 runtime and vendored ABC parser carry Apache-2.0 notices. Application source and dependency licenses are separate. Model licenses remain authoritative for permitted use.
