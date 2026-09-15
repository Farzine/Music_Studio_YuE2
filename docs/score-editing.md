# Score editing

YuE2 writes the composition it intends to perform as ABC notation before it
generates any audio. That score is an editable interface: change the notes or
the harmony, and regenerate from your version.

## Where the score is

Full Song and Melody Guided runs save `score/source.abc` inside the generation
directory and attach it to the generation. Open **View score** on a result, or
go to `/scores/<generation-id>`.

Direct Audio runs have no score — there is no plan to write.

## The dialect

This is a narrow, purpose-built subset, not general ABC. The studio validates
with the parser vendored from the YuE repository, so what the editor accepts is
exactly what the runtime accepts.

Required shape:

```abc
X:1
T:
M:4/4
L:1/16
Q:1/4=90
V: Vocal clef=treble name="Vocal Melody" snm="Vocal"
V: Ins clef=treble name="Ins Melody" snm="Inst."
K:D#m
% intro
V: Vocal
"D#m"z16|"D#m"z16|
V: Ins
Z|z2a'2a'2g'2g'2f'2f'2d'2|
```

* `X:1` and a **blank** `T:` header.
* Exactly two voices, `Vocal` and `Ins`.
* Chord symbols belong to `Vocal` only. A chord on `Ins` is rejected.
* Standard major and minor keys; explicit meter; durations from the supported
  set.
* `Z` is a full-measure rest; `z` with a length is an ordinary rest.

Validation failures name the problem rather than saying "invalid":

```text
Native chord symbols belong in Vocal, not Ins
Expected native X:1 and blank T: header
Unsupported chord 'Cmaj9'
% intro: event after the measure end
```

## Editing

1. Open the score workspace. **Edit** is your working copy; **Source** is the
   planner's original, always kept.
2. Make a change.
3. **Validate** — parses it the way the runtime will.
4. **Compare with source** — reports which musical invariants survived.
5. **Save edited score** — writes `score/edited.abc`. Refused if invalid.
6. **Regenerate from this score** — queues a new run with your ABC as the
   planner input, in the same project.

The source is never overwritten. Every regeneration is a new generation with its
own manifest, so you can compare takes.

## What `match: true` means

Comparison checks notes, timing, meter and tempo. Harmony is **deliberately
excluded** — reharmonising is the point of a harmony edit, not a corruption of
the score.

```text
match: true   melody, rhythm, meter and tempo are unchanged
match: false  the actual notes or their timing moved
```

So swapping every triad for its seventh gives `match: true`; raising one pitch
by a step gives `match: false`. Pass `allow_tempo_change` when a tempo change is
intended.

## A worked example: reharmonisation

Keep the melody, lyrics, style and seed fixed, and change only the chord
symbols:

```abc
V: Vocal
"C"c4e4g4e4|"F"f4a4c'4a4|      ← before
"Cmaj7"c4e4g4e4|"Fmaj7"f4a4c'4a4|  ← after
```

Compare (expect `match: true`), regenerate with the same seed, and listen to
both. Because everything else is pinned, the difference you hear is the harmony.

## Using an external score

Paste ABC into **Advanced → Song → ABC score** with Full Song or Melody Guided.
The planner uses your composition directly instead of writing one. Arbitrary ABC
from other tools usually needs converting to this dialect first; the validator
tells you what is wrong.

## Reproducibility

An edited-score run records the ABC in `request.json` and hashes every artifact
in `manifest.json`, so a generation always names the exact composition it sang.
Saved plans are content-checked when reloaded: change the file on disk and the
runtime refuses it, which is why edits are submitted as a new input rather than
written back over a saved plan.

## Not yet

Staff rendering, piano-roll editing and agent-driven edits are future work. The
MVP is deliberately raw ABC with real validation and real comparison, which is
what makes the round trip trustworthy.
