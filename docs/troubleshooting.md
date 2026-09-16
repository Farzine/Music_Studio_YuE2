# Troubleshooting

Every failure carries a code. The UI shows it with guidance; this page is the
longer version.

| Code | Means | What to do |
|---|---|---|
| `MODEL_NOT_FOUND` | The model or decoder directory is missing or incomplete. | Check `YUE2_MODEL_PATH` / `YUE2_VAE_PATH`, then run `./scripts/download_models.sh`. |
| `MODEL_LOAD_FAILED` | The weights exist but would not load. | Compare the files with `weights_manifest.json`; check the runtime versions on `/system`. |
| `CUDA_OOM` | The GPU ran out of memory at a specific stage. | See below. Your configuration was kept exactly as submitted. |
| `INVALID_CONFIG` | A value is out of range or a combination is impossible. | The message names the field. |
| `INVALID_ABC` | The score is not in the dialect the runtime accepts. | See [score-editing.md](score-editing.md). |
| `AUDIO_INPUT_ERROR` | The uploaded reference could not be read. | Check the file type and size. |
| `INFERENCE_FAILED` | The model runtime raised. | Read the job log on the generation page. |
| `DECODER_FAILED` | Decoding failed. | Switch to the tiled decoder, or reduce the tile size. |
| `ARTIFACT_WRITE_FAILED` | Files could not be written. | Check disk space and permissions on `DATA_DIR`. |
| `UNSUPPORTED_CAPABILITY` | A setting or mode the active backend does not offer. | The reason is in the message; `/system` lists every capability. |
| `CANCELLED` | You cancelled it. | — |

---

## CUDA out of memory

The studio never quietly lowers a setting to make a request fit. It reports the
stage that ran out, keeps the requested configuration in `failure.json`, and
leaves the next move to you.

What actually helps, roughly in order:

1. **Check you are on the right GPU.** On a shared machine the default card is
   often the busy one. The System page lists every GPU with its free memory and
   how much other processes are holding; pick a free one there. The change
   applies to the next job.

   Note that `CUDA_VISIBLE_DEVICES` in `.env` does **not** do this. That file is
   read into the application's settings, not exported into the worker's
   environment, so setting it there has no effect on which card CUDA uses. Use
   the System page, or export the variable in the worker's shell.

2. **Lower Maximum duration.** Memory scales with song length more than anything
   else.
3. **Use the tiled decoder.** Whole-song decoding holds the entire waveform. A
   30-second generation peaks around 7.2 GiB on an A6000; a long whole-song
   decode is where headroom disappears.
4. **Reduce the decoder tile size** — 1024 → 512 frames.
5. **Enable Offload AR weights.** Slower, noticeably lower peak.
6. **Lower the GPU memory budget** so the process reserves less, if something
   else is sharing the card.

The pre-flight warning on the Create screen is an estimate from free VRAM and
the decoder mode. It is labelled as an estimate and never blocks or changes a
request.

---

## The worker is offline

`/system` says so, and generations sit at `QUEUED`. Start it:

```bash
./scripts/dev_worker.sh
# or: make worker
```

It publishes a heartbeat to `data/worker/<worker-id>.json` every five seconds;
older than thirty seconds counts as offline.

## Generations stay queued although the worker is running

`MAX_CONCURRENT_GPU_JOBS` is 1 by default, so one job runs and the rest wait.
That is deliberate: it keeps VRAM predictable on a single GPU. The queue drawer
shows the position of each job.

## Cancellation seems slow

It is cooperative. The worker checks between tokens, solver steps and decoder
chunks, so it stops at the next safe boundary rather than instantly. The UI
shows *Cancellation requested…* for that interval. `CANCEL_POLL_INTERVAL_SECONDS`
controls how often the running job checks.

## A generation finished as "unfinished"

Status `INCOMPLETE`, error code `INCOMPLETE_TOKEN_LIMIT`. The model was still
mid-song when its token budget ran out, so the audio is part of a song. It is
kept and playable, and a short fade is applied to the cut so it does not click,
but it is deliberately **not** recorded as completed.

Why it can still happen after the budget check:

* **Direct Audio** writes no score, so there is nothing to predict the length
  from and the limit stands exactly as set. Raise Maximum duration and retry —
  the result page offers a one-click retry at roughly double the length reached.
* **Let the song finish is off.** With it on, a limit shorter than the planned
  song is raised automatically instead.
* The score under-ran its own estimate by more than the 15% tolerance, which is
  uncommon.

`truncated.abc` is a different thing: the *score* hit **ABC max tokens** before
it was finished, so the composition the song is built on is itself incomplete.
Raise ABC max tokens or shorten the lyrics.

## "This request does not fit the model's context window"

Error code `TOKEN_BUDGET_EXCEEDED`, refused before anything is queued. The
duration asked for, plus the instruction, style, lyrics and score, exceeds the
model's 24,576-token window. The message states the requested tokens, the
available tokens and the longest duration that does fit; the Create screen
offers to set that value.

This runtime generates a song in one autoregressive pass and exposes no
continuation, resume or audio-prefix entry point, so a longer song genuinely
cannot be assembled from segments. The remedies are real ones: a shorter
duration, or shorter lyrics to free context.

## torch does not see the GPU

```bash
.venv-yue2/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
nvidia-smi
```

If torch reports a CUDA version newer than your driver supports, reinstall it
from a matching index:

```bash
TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126 ./scripts/setup_yue2_env.sh
```

## Installing the worker environment times out

`pypi.nvidia.com` intermittently stalls on the large CUDA wheels. The setup
script retries; if it still gives up, run it again — completed downloads are
cached.

## FP8 is disabled

FP8 needs compute capability 8.9 or newer. An RTX A6000 is sm_86, so the option
is off and `/system` says why. The bf16 preset is the quality default anyway.

## Cover mode is disabled

Run `make cover`. It installs a private FFmpeg 7, the SheetSage2 weights, the
MERT encoder and a separate environment; the System page names whichever of
those is missing. See [cover-workflow.md](cover-workflow.md).

## A cover failed to transcribe

The error is `AUDIO_INPUT_ERROR` and carries the transcriber's own reason. The
full report is kept next to the generation at
`score/transcription/transcription.json`. A dense mix transcribes poorly; a
recording with a clear, prominent melody works best.

## The model selector will not open

Fixed. It was caused by an option whose value was the empty string, which a
select control reserves for "nothing selected". The default entry now uses an
explicit `default` sentinel, the component refuses an empty value outright in
development, and a test asserts no option the API serves can carry one.

## MP3 is unavailable

FFmpeg is not on `PATH`. FLAC and WAV are written by the runtime itself and
always work.

`make cover` installs a private FFmpeg 7 build into `tools/ffmpeg`, which the
studio prefers over anything on `PATH`. That build covers every download format.

## A download format is missing from the picker

The picker lists only formats the installed FFmpeg can actually write, because
offering one that would fail is worse than not offering it. The unavailable ones
are still listed under "formats unavailable on this machine", each with the
reason — usually a missing encoder.

What is needed for each:

| Format | Encoder |
|---|---|
| FLAC | `flac` |
| WAV | `pcm_s24le` |
| MP3 | `libmp3lame` |
| M4A | `aac` |
| OGG | `libvorbis` |

Check what your build has with
`./tools/ffmpeg/ffmpeg -hide_banner -encoders | grep -E "flac|lame|aac|vorbis|pcm_s24le"`.
The master's own format is always available; it needs no conversion at all.

## A download failed to convert

The response carries `ARTIFACT_WRITE_FAILED` with FFmpeg's own error. The partial
file is deleted rather than served — a download that claims a format is always
that format. Download the original FLAC instead, and convert it yourself if you
need to.

## A project will not delete

A generation inside it is still `QUEUED` or running, and the request is refused
with `409`. Deleting the directory under a running worker would leave it writing
into a folder that no longer exists. Cancel the generation, wait for it to settle
as `CANCELLED`, then delete the project.

## A deleted version's number was not reused

That is deliberate. Version numbers advance from a counter on the project, so
deleting version 2 leaves 1 and 3 as they are and the next take is version 4.
Reusing 2 would put two different takes at the same point in the history.

## Editing a project's configuration did not change an existing version

Also deliberate, and the reason the history is worth keeping. A project's
configuration is the starting point for its *next* version. Every version already
generated stores the exact settings it ran with, and nothing rewrites them. To
hear a change, press **Regenerate** on a version, edit whatever you like, and
generate a new one.

## Audio will not play or seek in the browser

The player decodes the file to draw a waveform. When the browser cannot decode
the container it falls back to a plain seek bar — playback still works, and
seeking uses HTTP range requests against `/api/v1/artifacts/{id}/audio`.

## Everything is gone after a restart

Check `DATA_DIR`. State lives entirely in that directory; nothing is held in
memory. Pointing at a different path shows an empty library.
