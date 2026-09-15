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

1. **Lower Maximum duration.** Memory scales with song length more than anything
   else.
2. **Use the tiled decoder.** Whole-song decoding holds the entire waveform. A
   30-second generation peaks around 7.2 GiB on an A6000; a long whole-song
   decode is where headroom disappears.
3. **Reduce the decoder tile size** — 1024 → 512 frames.
4. **Enable Offload AR weights.** Slower, noticeably lower peak.
5. **Lower the GPU memory budget** so the process reserves less, if something
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

## The result is marked truncated

The model reached its token ceiling before finishing. The audio is still valid
and usually playable; it may just end abruptly.

* `truncated.abc` — the plan hit **ABC max tokens**.
* `truncated.semantic` — the song hit **Maximum duration**.

Raise the relevant ceiling and regenerate with the same seed to compare.

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

It needs SheetSage2 and FFmpeg 6.1+. See [cover-workflow.md](cover-workflow.md).
The mode stays disabled with the reason attached rather than failing at
generation time.

## MP3 is unavailable

FFmpeg is not on `PATH`. FLAC and WAV are written by the runtime itself and
always work.

## Audio will not play or seek in the browser

The player decodes the file to draw a waveform. When the browser cannot decode
the container it falls back to a plain seek bar — playback still works, and
seeking uses HTTP range requests against `/api/v1/artifacts/{id}/audio`.

## Everything is gone after a restart

Check `DATA_DIR`. State lives entirely in that directory; nothing is held in
memory. Pointing at a different path shows an empty library.
