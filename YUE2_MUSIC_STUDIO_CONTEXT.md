# YUE2 MUSIC STUDIO — PROJECT CONTEXT

## 1. Project Intent

Build a professional, local-first web application for music generation using the open-source **YuE2-3B** model.

Primary user hardware:

- Linux workstation
- NVIDIA RTX A6000
- 48 GB VRAM
- local model inference
- no dependency on cloud GPU

The UI should be inspired by the interaction model of Suno: a simple music creation screen, custom lyrics/style inputs, advanced controls, playable generated songs, a history/library, generation queue, and iteration/regeneration.

It must NOT copy Suno source code, proprietary assets, branding, or protected implementation.

---

# 2. External References

## YuE repository

https://github.com/multimodal-art-projection/YuE

Official project repository.

Relevant concepts discovered in the current documentation:

- YuE2 full-song music generation
- lyrics + style driven generation
- symbolic planning
- ABC score representation
- cover workflows
- score editing
- YuE2-Vae listening decoder
- YuE2-Vae-legacy benchmark decoder
- reproducible generation artifacts
- local inference APIs

## YuE2-3B

https://huggingface.co/m-a-p/YuE2-3B

Model:

`m-a-p/YuE2-3B`

Current repository metadata indicates:

- model type: YuE2
- music generation
- text to audio/music
- symbolic planning
- editable score workflow
- Chinese and English support

The repository currently contains a `model.safetensors` file of approximately 7.26 GB.

## Comfy-Org YuE2

https://huggingface.co/Comfy-Org/YuE2/tree/main

Used as a reference for ComfyUI model/workflow assets.

## Suno

https://suno.com/

Used only as UX/product inspiration.

Relevant interaction concepts:

- custom creation mode
- lyrics input
- styles input
- advanced options
- song cards
- create action
- playable results
- regenerate/extend/refine concepts
- personal music workspace

---

# 3. Attached Workflow Source

Attached file:

`yue2_full.json`

This is the initial ComfyUI workflow reference.

Observed workflow metadata:

- workflow version: 0.4
- frontendVersion: 1.51.10
- 26 nodes
- 44 links

The workflow includes these key nodes:

- EmptyYuE2LatentAudio
- KSampler
- VAEDecodeAudio
- SaveAudioAdvanced
- PrimitiveNode for style
- PrimitiveNode for lyrics
- CheckpointLoaderSimple
- VAEDecodeAudioTiled
- AudioEncoderLoader
- SheetSage2AudioToABC
- LoadAudio
- YuE2GenerateMusic
- YuE2GenerateABC
- PreviewAny
- workflow notes

---

# 4. Exact Workflow Parameters Observed

## EmptyYuE2LatentAudio

Current workflow values:

```text
seconds = 120
batch_size = 1
```

These correspond to:

- requested latent/audio duration
- number of generated items in the latent batch

---

## KSampler

Current values:

```text
seed = 7
control_after_generate = fixed
steps = 32
cfg = 1
sampler_name = dpm_2
scheduler = sgm_uniform
denoise = 1
```

Inputs:

- model
- positive conditioning
- negative conditioning
- latent image

This is an important workflow-level synthesis control node.

Do not assume every KSampler setting is directly supported by the native YuE2 pipeline.

---

## VAEDecodeAudio

Produces decoded audio from latent data.

The workflow leaves its VAE input unconnected because another decoder path is used for the final saved audio.

---

## SaveAudioAdvanced

Current values:

```text
filename_prefix = audio/YuE2
format = flac
```

---

## CheckpointLoaderSimple

Current model:

```text
yue2_convrot_int8.safetensors
```

This is a Comfy-oriented checkpoint reference.

The application should not hard-code this filename.

Instead expose model selection dynamically.

---

## VAEDecodeAudioTiled

Current values:

```text
tile_size = 1920
overlap = 128
```

Workflow note says regular VAE decode may be faster when sufficient VRAM is available.

For a 48 GB RTX A6000, expose normal and tiled decoding as an advanced choice.

Do not assume normal decode always succeeds at every duration.

---

## AudioEncoderLoader

Current value:

```text
sheetsage2_bf16.safetensors
```

This supports the audio-to-ABC cover path.

---

## SheetSage2AudioToABC

Current value:

```text
mode = melody
```

The workflow converts input audio into an ABC representation.

---

## LoadAudio

Current test audio:

```text
test_ref.wav
```

Production UI should use user upload/reference audio instead of a hard-coded file.

---

## YuE2GenerateMusic

Current values:

```text
style =
violin with girl singing jpop anime

lyrics =
[verse]
fluff the fluffy tail
fluff the fluffy tail
fluff the fluffy tail
fluff the fluffy tail

[verse]
fluff the fluffy tail
fluff the fluffy tail
fluff the fluffy tail
fluff the fluffy tail

[verse]
fluff the fluffy tail
fluff the fluffy tail
fluff the fluffy tail
fluff the fluffy tail

abc = ""

seed = 17
control_after_generate = fixed
mode = full
max_duration = 360
temperature = 1
top_p = 0.95
top_k = 100
repetition_penalty = 1.2
```

This is the main user-facing music-generation configuration.

---

## YuE2GenerateABC

Current values:

```text
style =
violin with girl singing jpop anime

lyrics =
same test lyrics

seed = 10
control_after_generate = fixed
mode = full
max_abc_tokens = 8192
```

This provides symbolic/ABC planning.

---

# 5. Workflow Graph

Conceptual path for standard generation:

```text
style
lyrics
      \
       -> YuE2GenerateMusic
               |
               +--> conditioning
               |
               +--> seconds
                         |
                         v
                    EmptyYuE2LatentAudio
                         |
                         v
                      KSampler
                         |
                         v
                 VAEDecodeAudioTiled
                         |
                         v
                    SaveAudioAdvanced
```

Model/conditioning path:

```text
CheckpointLoaderSimple
        |
        +--> MODEL -> KSampler
        |
        +--> CLIP -> YuE2GenerateMusic
```

Cover path:

```text
LoadAudio
    |
    v
SheetSage2AudioToABC
    |
    v
ABC
    |
    v
YuE2GenerateMusic
```

This cover path is explicitly described by the workflow notes.

---

# 6. Native YuE2 Runtime Context

Current public YuE2 documentation indicates a native inference runtime rather than requiring the application to drive ComfyUI.

Important current concepts:

- YuE2-3B
- YuE2-Vae
- YuE2-Vae-legacy
- `YuE2Pipeline`
- `style`
- `lyrics`
- `cot`
- `seed`
- `abc`
- `cfg_scale`
- model/VAE revisions
- local directories
- `local_files_only`
- artifact saving
- score/ABC retention
- planning and audio generation stages

The current documented baseline is a BF16-capable NVIDIA GPU with approximately 24 GB VRAM and one active request.

The target RTX A6000 has 48 GB VRAM, so it is a strong local target.

---

# 7. Native YuE2 Modes

Current conceptual modes from documentation:

### Full

Generate melody, harmony and audio from style + lyrics using symbolic planning.

### Melody

Generate melody first and then audio; useful when accompaniment should remain freer.

### Off

Generate audio without symbolic planning where supported.

### Cover

Use audio transcription to create a melody/ABC representation and feed it back into YuE2.

### Score Edit

Generate or load ABC, edit the score, then regenerate.

The UI must only expose modes supported by the actual installed runtime.

---

# 8. Current Generation Configuration Context

Current YuE2 published generation config contains concepts such as:

```json
{
  "abc": {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 30,
    "repetition_penalty": 1.005,
    "penalty_window": 100,
    "min_tokens": 32,
    "max_tokens": 4096
  },
  "semantic": {
    "temperature": 1.0,
    "top_p": 0.95,
    "top_k": 100,
    "repetition_penalty": 1.2,
    "penalty_window": 50,
    "min_tokens": 200,
    "max_tokens": 9000
  },
  "ode_steps": 32,
  "ode_method": "midpoint",
  "context": 24576,
  "version": "yue2-native-v1"
}
```

This is important because the Comfy workflow and native runtime may expose overlapping but not identical controls.

Architecture must therefore have a parameter-adapter layer.

---

# 9. Important Native-vs-Comfy Distinction

Do not assume:

```text
Comfy KSampler parameter
==
native YuE2 parameter
```

or:

```text
Comfy checkpoint
==
native model directory
```

Instead:

```text
User UI
  ->
GenerationConfig
  ->
Capability/Mapping Layer
  ->
Native YuE2 Adapter
```

and optionally:

```text
GenerationConfig
  ->
Comfy Workflow Adapter
```

This allows one frontend to work across compatible backends.

---

# 10. Licensing Context

Current YuE2 checkpoint weights are licensed:

**CC BY-NC 4.0**

This applies to the YuE2 model weights identified in the current license documentation.

The code/project and third-party assets may have different licenses.

Therefore:

- record licenses
- preserve attribution
- show a license page
- do not claim unrestricted commercial rights
- keep model licensing separate from application source licensing
- inspect third-party licenses before redistribution

---

# 11. Recommended System Architecture

```text
                      ┌─────────────────────┐
                      │     Next.js UI      │
                      │  Suno-inspired UX   │
                      └──────────┬──────────┘
                                 │
                            REST / WS
                                 │
                      ┌──────────▼──────────┐
                      │      FastAPI        │
                      │   Domain + API      │
                      └──────────┬──────────┘
                                 │
                         Job + Config
                                 │
                      ┌──────────▼──────────┐
                      │    Job Queue        │
                      │ local-first         │
                      └──────────┬──────────┘
                                 │
                         one GPU worker
                                 │
                 ┌───────────────▼───────────────┐
                 │      YuE2 Worker Process      │
                 │                               │
                 │ Model Manager                 │
                 │ Native YuE2 Adapter           │
                 │ Optional SheetSage2 Adapter   │
                 │ VAE Decoder                   │
                 └───────────────┬───────────────┘
                                 │
                           Artifacts
                                 │
                 ┌───────────────▼───────────────┐
                 │ Local Artifact Store           │
                 │ audio / ABC / latent / logs   │
                 └──────────────────────────────┘
                                 │
                         SQLite metadata
```

---

# 12. Why a Queue Exists

YuE2 can use substantial VRAM for long sequences.

The target GPU is powerful, but it is still one GPU.

Default:

```text
max_concurrent_gpu_jobs = 1
```

This keeps memory predictable and enables a clean path to future multi-GPU workers.

---

# 13. Suggested Repository Layout

```text
yue2-music-studio/
├── apps/
│   └── web/
│
├── services/
│   ├── api/
│   ├── yue2_worker/
│   └── sheetsage2_worker/
│
├── packages/
│   ├── shared-types/
│   ├── config-schema/
│   └── workflow-schema/
│
├── configs/
├── scripts/
├── tests/
├── docs/
├── data/
├── .env.example
├── Makefile
└── README.md
```

---

# 14. Frontend Pages

Recommended pages:

```text
/
  Dashboard / recent music

/create
  Main music creation screen

/library
  All generated songs

/projects/[id]
  Project workspace

/generations/[id]
  Generation details

/scores/[id]
  ABC / score workspace

/settings
  Application settings

/system
  GPU/model/worker system information

/about
  Model and license information
```

---

# 15. Create Screen Information Architecture

### Basic

- title
- style
- lyrics
- mode
- create button

### Advanced

- model
- VAE
- seed
- seed behavior
- temperature
- top-p
- top-k
- repetition penalty
- maximum duration
- ABC planning options
- sampler
- scheduler
- steps
- CFG
- denoise
- decoder
- tile size
- overlap
- output format

Not every option needs to appear on the first screen.

---

# 16. Generation Result

Each result should retain:

- audio
- exact request
- exact effective config
- model revision
- VAE revision
- seed
- mode
- duration
- score if available
- timestamps
- hardware/runtime information
- logs
- warnings
- failure reason if unsuccessful

---

# 17. Artifact Layout

Recommended:

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
          audio/
            final.flac
          score/
            source.abc
            edited.abc
          intermediates/
          logs/
            generation.log
```

---

# 18. API Contract Concepts

```text
GET    /api/v1/health
GET    /api/v1/system/info
GET    /api/v1/models
GET    /api/v1/models/capabilities
GET    /api/v1/generation/schema

POST   /api/v1/projects
GET    /api/v1/projects
GET    /api/v1/projects/{id}

POST   /api/v1/generations
GET    /api/v1/generations/{id}
POST   /api/v1/generations/{id}/cancel
POST   /api/v1/generations/{id}/retry
POST   /api/v1/generations/{id}/duplicate

GET    /api/v1/artifacts/{id}

GET    /api/v1/scores/{id}
POST   /api/v1/scores/{id}/validate
POST   /api/v1/scores/{id}/compare
```

Realtime:

```text
/ws/jobs/{job_id}
```

---

# 19. Database Entities

At minimum:

```text
Project
Generation
GenerationConfig
Artifact
Score
Preset
Job
SystemSnapshot
```

Database should hold metadata.

Audio and latent files stay on filesystem/object-store abstraction.

---

# 20. Engineering Principles

Always prioritize:

1. Correctness
2. Reproducibility
3. Clean separation of concerns
4. Good UX
5. Performance
6. Scalability

Never:

- put inference inside React
- put model code inside FastAPI route handlers
- hard-code model paths
- reload models for every request
- silently ignore user parameters
- silently alter requested settings
- expose fake progress numbers
- invent unsupported YuE2 features

---

# 21. First Implementation Milestone

The first working version should be:

```text
Next.js
   ->
FastAPI
   ->
one local worker
   ->
YuE2-3B
   ->
YuE2-Vae
   ->
audio file
   ->
browser player
```

with:

- title
- style
- lyrics
- mode
- seed
- temperature
- top-p
- top-k
- repetition penalty
- duration
- basic generation settings
- job status
- result history

Then add:

- advanced KSampler/workflow controls
- ABC planning
- cover
- score editing
- presets
- system monitoring
- scalable queue backend

---

# 22. Key Product Philosophy

The user should feel like:

> "I am making music."

not:

> "I am operating an ML pipeline."

The complexity belongs behind an Advanced Settings boundary.

At the same time, advanced users must never be prevented from controlling supported generation parameters.

That balance is the central UX requirement.

---

# 23. Important Source Facts to Preserve

From the current YuE project:

- YuE2 is intended for full-song generation.
- It supports editable symbolic plans.
- YuE2 can be used for style + lyrics driven generation.
- Audio-to-ABC can be used for cover workflows.
- Score editing can drive regeneration.
- Native YuE2 runtime and ComfyUI workflow are related but should not be conflated.
- The current baseline is designed for a substantial NVIDIA GPU and one active request.
- A 48 GB RTX A6000 is a strong local target.
- Current YuE2 checkpoint weights have a non-commercial CC BY-NC 4.0 license.

---

# 24. Main Reference Files

Project-specific files:

```text
yue2_full.json
YUE2_MUSIC_STUDIO_BUILD_PROMPT.md
YUE2_MUSIC_STUDIO_CONTEXT.md
```

Use the build prompt together with this context file when asking another coding AI/agent to implement the project.

