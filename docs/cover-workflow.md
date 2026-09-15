# Cover workflow

A cover starts with a readable composition: transcribe the recording, review the
melody, then ask YuE2 to realise it in a new style.

```text
reference audio ──► SheetSage2 ──► melody ABC ──► review/edit ──► YuE2 (cot=melody)
```

## Status on this machine

**Disabled.** The Create screen shows the mode greyed out and `/system` gives the
reason. The capability check is real, not a placeholder:

* `m-a-p/SheetSage2` must exist at `SHEETSAGE2_MODEL_PATH`.
* FFmpeg **6.1 or newer** must be on `PATH`. Ubuntu 22.04 ships 4.4.2, which is
  not sufficient.

Until both hold, the mode is not offered. This is deliberate: a mode that would
fail at generation time should not be presented as available.

## Enabling it

SheetSage2 and YuE2 pin incompatible dependency versions, so SheetSage2 gets its
own environment and the two exchange files. Run them sequentially — they share
one GPU.

### 1. FFmpeg 6.1+

Ubuntu 22.04 needs a newer build than the archive provides — a static build or a
backport both work. Verify:

```bash
ffmpeg -version | head -1
```

### 2. A separate environment

```bash
python3.11 -m venv .venv-sheetsage2
.venv-sheetsage2/bin/python -m pip install huggingface-hub==0.36.0
.venv-sheetsage2/bin/huggingface-cli download m-a-p/SheetSage2 --local-dir models/SheetSage2
.venv-sheetsage2/bin/python -m pip install torch==2.8.0 torchaudio==2.8.0 \
  --index-url https://download.pytorch.org/whl/cu126
.venv-sheetsage2/bin/python -m pip install -r models/SheetSage2/requirements.txt
```

Loading SheetSage2 pulls in the MERT-v2-FullSong encoder its configuration
selects; no separate feature-extraction step is needed.

### 3. Point the studio at it

```env
SHEETSAGE2_MODEL_PATH=./models/SheetSage2
```

Restart the API. `/system` should now show `cover: on`, and Cover appears on the
Create screen.

## Using it

1. Choose **Cover** and drop in a reference file (WAV, FLAC, MP3, OGG, M4A,
   AIFF). The panel shows its duration once the file is probed.
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

## In the ComfyUI reference workflow

The same path exists as `LoadAudio → SheetSage2AudioToABC (mode: melody) →
YuE2GenerateMusic`, bypassed in the saved graph. The `AudioEncoderLoader` node
there points at `sheetsage2_bf16.safetensors`; the native runtime loads the
model directory instead. Both are recorded in `configs/workflow-mapping.json`.
