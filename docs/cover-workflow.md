# Cover workflow

A cover starts with a readable composition: transcribe the recording, review the
melody, then ask YuE2 to realise it in a new style.

```text
reference audio ──► SheetSage2 ──► melody ABC ──► review/edit ──► YuE2 (cot=melody)
```

## Installing it

```bash
make cover      # or: ./scripts/setup_cover.sh
```

That does four things, all of which the capability check then verifies:

1. **A private FFmpeg 7.** SheetSage2 needs 6.1 or newer and Ubuntu 22.04 ships
   4.4.2, so a static build is installed under `tools/ffmpeg/` rather than
   touching the system one. The worker puts it at the front of the subprocess's
   `PATH`.
2. **The SheetSage2 weights** into `models/SheetSage2`, without the
   notation-rendering assets, which transcription does not need.
3. **The MERT-v2-FullSong encoder** into the Hugging Face cache. SheetSage2's
   configuration selects it by repository id, so it has to be cached for
   offline transcription to work.
4. **`.venv-sheetsage2`**, a separate environment. SheetSage2 pins torch 2.8.0
   and transformers 4.45.2; YuE2 pins 2.10.0 and 4.57.6. They cannot share an
   interpreter.

Restart the API afterwards. `/system` shows `cover: on`, and Cover becomes
selectable on the Create screen.

Until all four are present the mode is offered but disabled, with the specific
thing that is missing written next to it — a mode that would fail at generation
time should not look available.

## How it runs

```text
upload ──► services/sheetsage2_worker/transcribe.py   (.venv-sheetsage2, subprocess)
              │ melody-only ABC + warnings, as JSON
              ▼
           YuE2 native adapter, cot=melody           (.venv-yue2)
```

The two never share a process. The worker launches the transcriber with an
argument list — never a shell string — pins it to the selected GPU with
`CUDA_VISIBLE_DEVICES`, and reads back one JSON report that always exists, so a
failure never has to be recovered from stderr.

Transcription runs **before** the YuE2 weights are loaded, so the two models are
not resident on the same card at once. It appears in the UI as its own
`TRANSCRIBING` stage, reporting real window counts from the encoder.

Measured on an RTX A6000: a 30-second reference transcribes and generates a
40-second cover in about 90 seconds end to end.

## Using it

1. Choose **Cover** and drop in a reference file (WAV, FLAC, MP3, OGG, M4A,
   AIFF, up to 100 MB). The panel shows its duration, sample rate and channels
   once the file is probed, and lets you play it back before committing.
2. The audio is transcribed to a melody-only score — vocal and instrumental
   melodies, no chord symbols.
3. **Review the score before generating.** Transcription is not exact, and
   transcription errors carry straight into the cover. Any warnings it produces
   are shown; open the score workspace to read and correct the notation.
4. Write the lyrics and the target style. Align the section tags and lyric order
   with the score. When translating, match phrasing and syllable counts to the
   melody.
5. Generate. The mode maps to the native `cot=melody` path with your reviewed
   ABC as the planner input.

## Notes

* Transcription accuracy varies with the recording. A dense mix transcribes less
  cleanly than a sparse one.
* The cover path uses the general YuE2 checkpoint. There is no cover-specific
  fine-tune.
* The reference audio is kept under `data/uploads/`. It is never re-encoded and
  never leaves the machine.
* The reference recording carries its own rights. Transcribing and re-recording
  it does not change that, and the model weights are non-commercial
  ([licensing.md](licensing.md)).

## When it fails

Every failure is reported as `AUDIO_INPUT_ERROR` with the transcriber's own
reason, and the full report is kept at
`…/generations/<id>/score/transcription/transcription.json`.

Common causes:

* **No usable melody found.** A dense or heavily produced mix can defeat
  transcription. Try a sparser recording.
* **The encoder is not cached.** Run `make cover` again; step 3 fetches it.
* **The run exceeded `SHEETSAGE2_TIMEOUT_SECONDS`** (30 minutes by default).

## In the ComfyUI reference workflow

The same path exists as `LoadAudio → SheetSage2AudioToABC (mode: melody) →
YuE2GenerateMusic`, bypassed in the saved graph. The `AudioEncoderLoader` node
there points at `sheetsage2_bf16.safetensors`; the native runtime loads the
model directory instead. Both are recorded in `configs/workflow-mapping.json`.
