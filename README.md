# YuE2 Music Studio

A local-first music creation studio built on the open **YuE2-3B** model. Style and
lyrics go in, a full song comes out, and every generation keeps the exact
settings, the symbolic score and a manifest that explains what produced it.

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
| Stages | transcribe (covers) → plan → acoustic tokens → synthesis → decode, each reported separately |
| Limits | 24,576-token window read from the checkpoint; 25 tokens per second of audio, so ~13–16 min of song once the prompt is subtracted |
| GPUs | every card is listed on the System page with its free memory; pick one there, no restart |

Modes: **Full Song**, **Melody Guided**, **Direct Audio**, **Score Edit** and
**Cover**. Cover transcribes a recording you supply into a melody score with
SheetSage2 and realises it in your style; install it with `make cover` and the
System page will show it switched on. Anything not installed stays visible but
disabled with the specific reason, rather than quietly missing.

---

## Quick start

```bash
git clone <this repo> && cd yue2-music-studio

make install          # .venv-api, .venv-yue2 and the frontend
make models           # ~7.8 GB of weights into ./models
make cover            # optional: SheetSage2 + FFmpeg 7 for the cover workflow
cp .env.example .env  # adjust paths if your models live elsewhere

make smoke-test       # prove the GPU path works before opening a browser
make dev              # API + worker + frontend
```

Then open <http://127.0.0.1:3000>.

Without `make`:

```bash
./scripts/setup_api_env.sh
./scripts/setup_yue2_env.sh
./scripts/download_models.sh
cd apps/web && npm install && cd ../..

./scripts/dev_api.sh --reload                      # terminal 1
./scripts/dev_worker.sh                            # terminal 2
npm --prefix apps/web run dev                      # terminal 3
```

Full instructions, including driver and CUDA specifics:
[docs/setup-linux.md](docs/setup-linux.md).

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

---

## The three rules this project is built around

**1. Parameters are defined once.** `configs/parameter-registry.json` describes
every setting — its range, its help text, its native equivalent and its ComfyUI
origin. The API serves it at `/api/v1/generation/schema`, the frontend renders
forms from it, the worker validates against it, and `configs/workflow-mapping.json`
is generated from it. No parameter is described twice.

**2. Nothing is silently dropped or substituted.** The ComfyUI workflow exposes
`sampler_name`, `scheduler`, `denoise`, `seconds` and `batch_size`. The native
runtime has no equivalent for any of them. Setting one is refused with the
reason, and the UI shows the control disabled with that reason attached —
it is never accepted and then ignored.

**3. A fragment is never sold as a song.** The model decides how long a song
is; the duration setting is a hard stop, not a target. The studio counts context
with the checkpoint's own tokenizer, reads the written score's own length before
any audio is generated, and then either raises the limit so the song can finish
— reporting the change — or refuses before spending the GPU time. A run that
does get cut off ends as `INCOMPLETE`, never `COMPLETED`. See
[docs/parameter-guide.md](docs/parameter-guide.md#how-duration-really-works).

**4. Progress is never invented.** Token stages report real counts and a rate,
with no percentage, because a generation limit is a ceiling and not a target.
Stages that do have a target — ODE solver steps, decoder chunks, transcription
windows — report a real percentage.

**5. Every setting explains itself.** All 46 parameters carry plain-language
help served by the backend: what it is, what happens if you raise or lower it,
what is recommended, what an extreme value does, and whether it costs time or
memory. It appears behind an ⓘ beside the label — or a ⚠ for the seventeen
settings where an unusual value genuinely destabilises output, inflates VRAM or
lengthens a run. Hover on a desktop, tap on a phone, or reach it with the
keyboard. See [docs/parameter-guide.md](docs/parameter-guide.md).

---

## Choosing a GPU

On a machine with more than one card, or one shared with other work, the System
page lists every GPU with its free memory, its utilisation and how much other
processes are holding, and lets you pick which one loads the model. The choice
is stored in `data/runtime-settings.json` and applies to the next generation; a
run already in flight finishes on the card it started on.

`CUDA_VISIBLE_DEVICES` in `.env` does **not** control this, and never did — that
file is read into the application's settings, not exported into the worker's
process environment. Use the System page, or export the variable in the shell
that starts the worker if you want to hide cards entirely.

## Reproducibility

Every completed generation writes `manifest.json` containing the request as
submitted, the effective configuration, per-file SHA-256 of the model and
decoder weights, the runtime versions, the GPU, the timings and the peak VRAM.
The seed that was actually used is always recorded, including when the studio
drew it.

```jsonc
{
  "schema_version": 1,
  "weights": { "mot": { "files": { "model.safetensors": { "sha256": "1d55c42c…" } } } },
  "runtime":  { "torch": "2.10.0+cu126", "yue2-infer": "0.1.6", "latent_frame_rate": 25 },
  "timing":   { "planning_seconds": 10.9, "decode_seconds": 3.0, "gpu_peak_bytes": 7777752064 }
}
```

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

The YuE2 checkpoint weights are **CC BY-NC 4.0** — non-commercial. That covers
the weights and what you do with their output; it is separate from this
application's source. The YuE2 runtime and the vendored ABC parser are
Apache-2.0. Details in [docs/licensing.md](docs/licensing.md) and on the
in-app About page.
