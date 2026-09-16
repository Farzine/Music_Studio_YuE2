# Parameter guide

Every control, in plain language.

You do not need this page to use the application: the same explanations are
served with the schema and appear in the interface behind the small icon beside
each label. Hover it on a desktop, tap it on a phone, or reach it with the
keyboard — one component handles all three, so the behaviour is identical
everywhere.

* **ⓘ** — ordinary information.
* **⚠** — an unusual value here genuinely destabilises output, inflates VRAM or
  lengthens a run. Seventeen of the forty-six settings carry it; the rest do
  not, so the symbol keeps its meaning.

Each entry answers the same questions: what it is, what happens if you raise or
lower it, what is recommended, what an extreme value does, and whether it costs
time or memory. Fields that do not apply are simply absent rather than padded.

This page is the prose version of `configs/parameter-registry.json`, which is
the single definition of every parameter — the API serves it, the frontend
renders forms from it, the worker validates against it and the ComfyUI mapping
is generated from it.

Each parameter is one of four kinds:

* **model** — changes what the model does.
* **ComfyUI workflow** — exists in the reference workflow; the native runtime has
  no equivalent, so the studio refuses it instead of ignoring it.
* **post-processing** — happens after generation, to the file.
* **studio** — handled by the application before the request reaches the model.

---

## Song

### Style
What the music should be. Genre, instruments, vocal character, language and
tempo all help. Write it like a brief, not a keyword list:

> Cinematic Bengali folk-pop, warm male vocal, acoustic guitar, bamboo flute,
> organic drums, melancholic but hopeful, 92 BPM

### Lyrics
The words to sing, with section tags on their own line: `[Intro]`, `[Verse]`,
`[Pre-Chorus]`, `[Chorus]`, `[Bridge]`, `[Outro]`. These are the tags the model
was trained on; inventing others does not create new behaviour.

### Mode

| Mode | What happens |
|---|---|
| **Full Song** | Writes a chord-annotated score, then sings it. The default. |
| **Melody Guided** | Writes a melody only, leaving the accompaniment freer. |
| **Direct Audio** | No score at all. Faster, less structured. |
| **Cover** | Transcribes reference audio into a melody, then realises it in your style. |
| **Score Edit** | Regenerates from a score you edited. |

### ABC score
An external composition used instead of a generated plan. Requires Full Song or
Melody Guided. The dialect is narrow: native `X:1`, blank `T:`, two voices named
`Vocal` and `Ins`, chord symbols on `Vocal` only. Anything else is rejected with
the parser's own reason.

---

## Model

| Control | What it does |
|---|---|
| **Model** | Which local YuE2 directory to load. Leave on the default for `.env`. |
| **Model revision** | Pins a Hugging Face revision. No effect on a local directory. |
| **Decoder weights** | `YuE2-Vae` for listening, `YuE2-Vae-legacy` to reproduce the published benchmark. |
| **Compute backend** | `torch` uses CUDA graphs; `torch-eager` is the debugging fallback; `vllm` needs the optional extras. |
| **Quantization** | `none` is bf16 and is the quality default. FP8 needs compute capability 8.9+. |
| **Offload AR weights** | Moves the autoregressive weights off the GPU during synthesis. Slower, lower peak. |
| **GPU memory budget** | Caps this process's allocation and picks the decoder chunk size. 24 is the documented baseline; 40 suits a 48 GB card. |
| **Offline** | Never contacts Hugging Face during a generation. |

---

## Planning

These shape the symbolic score written before any audio exists.

| Control | Default | What it does |
|---|---|---|
| **Planner temperature** | 0.7 | Lower keeps the composition conventional. |
| **Planner top-p** | 0.9 | Nucleus cutoff. |
| **Planner top-k** | 30 | Candidate cap per step. |
| **Planner repetition penalty** | 1.005 | Nearly neutral on purpose — scores repeat by design. |
| **Planner penalty window** | 100 | How far back the penalty looks. |
| **Planner minimum tokens** | 32 | Stops the plan ending immediately. |
| **ABC max tokens** | 4096 | Ceiling on plan length. Hitting it marks the result truncated rather than failing. |
| **Planner seed** | — | *ComfyUI only.* The native pipeline derives both stages from one request seed. Use **Seed**. |

---

## Generation

| Control | Default | What it does |
|---|---|---|
| **Seed** | 831001 | The same seed, settings and weights reproduce a generation. |
| **Seed behaviour** | Fixed | `Randomize` draws a seed on the server; `Increment` adds one after each run. The seed actually used is always saved. |
| **Temperature** | 1.0 | Higher is more adventurous and less stable. |
| **Top-p** | 0.95 | Keeps the most likely tokens that together reach this probability. |
| **Top-k** | 100 | Hard cap on candidates per step. |
| **Repetition penalty** | 1.2 | Pushes the model away from looping. |
| **Penalty window** | 50 | How far back that penalty looks. |
| **Minimum tokens** | 200 | Floor on length — 25 tokens is one second, so 200 is eight seconds. |
| **Maximum duration** | 360 s | A ceiling, not a target. The model stops when the song is done. |
| **Semantic max tokens** | — | Set the ceiling in tokens directly instead of deriving it from the duration. |

### How duration works

The decoder runs at 48000 Hz with a downsampling ratio of 1920, so there are
exactly **25 latent frames per second**, and the acoustic stage emits one token
per frame:

```text
seconds = tokens / 25
```

360 seconds is 9000 tokens — which is why the runtime default and the ComfyUI
workflow's `max_duration = 360` are the same limit expressed two ways. Raising
the ceiling does not make a song longer; it only stops a long one being cut off.
If the model does hit the ceiling, the result is marked **truncated** and the
warning says so.

---

## Acoustic synthesis

| Control | Default | What it does |
|---|---|---|
| **Guidance (CFG)** | runtime default | How strongly text and score steer the audio. Empty means 1.0 with a plan, 1.01 without. |
| **Synthesis steps** | 32 | Solver steps turning tokens into latents. More costs time; 32 is the validated setting. |
| **Solver** | midpoint | Fixed by the runtime protocol. |
| **Sampler** | — | *ComfyUI only.* No sampler list exists natively. |
| **Scheduler** | — | *ComfyUI only.* The schedule is uniform. |
| **Denoise** | — | *ComfyUI only.* The full trajectory is always solved. |
| **Latent length** | — | *ComfyUI only.* Latents are sized from the tokens actually emitted. |
| **Batch size** | — | *ComfyUI only.* One call, one candidate — queue several jobs for variations. |

---

## Decoder

| Control | Default | What it does |
|---|---|---|
| **Decoder mode** | Tiled | Tiled decodes in chunks with predictable memory. Whole-song is faster when VRAM allows, and is not guaranteed to fit at every length. |
| **Tile size** | 1024 frames | Latent frames per chunk; 25 frames is one second. Smaller uses less memory and takes longer. |
| **Tile overlap** | 16 | Fixed by the runtime. Shown for completeness. |

---

## Output

| Control | Default | What it does |
|---|---|---|
| **Format** | FLAC | FLAC (24-bit) and WAV (32-bit float) are written by the runtime itself. MP3 is an explicit FFmpeg conversion made afterwards. |
| **Filename prefix** | YuE2 | Used for downloads. On-disk paths are derived from ids and never change. |
| **Keep the lossless master** | on | The model's own output is always retained untouched. |

---

## Presets

A preset is a saved configuration object merged over the defaults — there is no
hidden behaviour attached to one.

| Preset | What it changes |
|---|---|
| **Balanced** | Nothing. The runtime's validated settings. |
| **High Quality** | 64 solver steps, whole-song decode. |
| **Fast Preview** | 60 s, 16 steps, smaller plan, small tiles. A sketch, not a preview of final quality. |
| **Low VRAM** | 24 GiB budget, AR offload, 512-frame tiles. |

Select one, change anything, and save it as your own from the Create screen.
