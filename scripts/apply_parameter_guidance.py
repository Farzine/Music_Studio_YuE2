"""Add plain-language guidance to every parameter in the registry.

Every entry answers: what is it, what happens if I raise or lower it, what is
recommended, what an extreme value does, and whether it costs time or memory.
Only statements true for this backend are included. `severity` is "caution"
only where an unusual value genuinely destabilises output, inflates VRAM, or
lengthens a run.
"""
import json
from pathlib import Path

REGISTRY = Path("configs/parameter-registry.json")

G = {
"prompt.style": dict(severity="info",
  what="The brief for the music: genre, instruments, the kind of voice, the language and the tempo. This is the single strongest influence on what you get back.",
  more="A richer description with instruments and a tempo gives the model much more to work with.",
  less="A bare description such as 'pop' leaves almost every decision to the model, so results vary wildly between runs.",
  recommended="One or two lines. Name the genre, two or three instruments, the vocal character and a BPM.",
  cost="No effect on generation time."),

"prompt.lyrics": dict(severity="info",
  what="The words to be sung, with section tags such as [Verse] and [Chorus] on their own lines. The tags tell the model where the song's structure changes.",
  more="More sections give a longer, more structured song, up to the duration ceiling.",
  less="Very short lyrics tend to produce a short song, or repeated material to fill the time.",
  recommended="Use the section tags the model was trained on. Inventing new tag names does not create new behaviour.",
  cost="Very long lyrics crowd the context window and can lead to a truncated plan."),

"prompt.mode": dict(severity="info",
  what="How much of the composition the model plans before it sings a note. Full Song writes a chord-annotated score first; Melody Guided writes only a melody; Direct Audio skips planning entirely; Cover transcribes a recording you supply; Score Edit regenerates from a score you edited.",
  more="Planning modes give more coherent structure and give you an editable score afterwards.",
  less="Direct Audio is quicker and less structured, and produces no score to edit.",
  recommended="Full Song unless you have a reason to do otherwise.",
  cost="Planning adds roughly ten seconds before audio generation begins."),

"prompt.abc": dict(severity="caution",
  what="A composition in ABC notation used instead of one the model writes. The model performs this material rather than inventing its own.",
  more="Supplying a score gives you exact control over melody and harmony.",
  less="Leaving it empty lets the model compose freely.",
  recommended="Leave empty unless you are editing a score the model produced.",
  extremes="The dialect is narrow: native X:1, a blank T: header, two voices named Vocal and Ins, and chord symbols on Vocal only. Anything else is refused with the parser's reason.",
  cost="Skips the planning stage, so a run is slightly faster."),

"prompt.reference_upload_id": dict(severity="caution",
  what="The recording a cover is based on. It is transcribed into a melody score, which then guides generation in your chosen style.",
  recommended="A clear recording with a prominent melody transcribes best.",
  extremes="Transcription is not exact. A dense or noisy mix transcribes poorly, and those errors carry straight into the cover. Review the score before you rely on the result.",
  cost="Transcription adds a separate pass on the GPU before generation starts."),

"model.checkpoint": dict(severity="caution",
  what="Which set of model weights to generate with. Different checkpoints are trained or quantised differently, so they sound different and can need different amounts of VRAM.",
  recommended="Leave on Default unless you have deliberately installed another checkpoint.",
  extremes="Selecting a model whose files are missing fails the run immediately rather than falling back to another one.",
  cost="Switching models mid-session unloads the resident weights and reloads about 7 GB, which costs several seconds on the next run."),

"model.revision": dict(severity="info",
  what="Pins a specific published version of the model when it is fetched from Hugging Face, so a comparison months apart uses identical weights.",
  recommended="Leave empty. It has no effect on a local model directory, where the file hashes recorded in each manifest are the identity.",
  cost="None."),

"model.vae": dict(severity="info",
  what="The decoder that turns the model's internal representation into audio you can hear. The standard decoder is tuned for listening; the legacy one exists to reproduce the published benchmark numbers.",
  recommended="Standard, unless you are reproducing a benchmark.",
  cost="No meaningful difference in time."),

"model.vae_revision": dict(severity="info",
  what="Pins a published version of the decoder, for the same reason as the model revision.",
  recommended="Leave empty.",
  cost="None."),

"model.compute_backend": dict(severity="caution",
  what="How the model's token generation is executed. Torch with CUDA graphs is the fast default; eager mode is slower but easier to debug; vLLM is an optional high-throughput path.",
  recommended="Torch.",
  extremes="Eager mode is noticeably slower. vLLM needs extra packages installed in the worker environment, and the option stays disabled until they are.",
  cost="Eager mode increases generation time."),

"model.quantization": dict(severity="caution",
  what="Whether the weights are compressed to a smaller numeric format before running. Compression saves memory at some cost to fidelity.",
  more="FP8 lowers VRAM use on hardware that supports it.",
  less="None keeps full bf16 precision and is the quality default.",
  recommended="None. With 48 GB there is no need to compress.",
  extremes="FP8 needs a GPU with compute capability 8.9 or newer; on older cards the option is disabled rather than silently ignored.",
  cost="Lowers VRAM; may slightly change how the output sounds."),

"model.offload_ar": dict(severity="caution",
  what="Moves the text-and-planning half of the model off the GPU while audio is being synthesised, freeing memory for the part that is actually working.",
  more="Turning it on lowers the peak VRAM a run needs.",
  less="Leaving it off keeps everything resident and is faster.",
  recommended="Off, unless you are sharing the GPU or hitting out-of-memory errors.",
  cost="Adds time to every run because weights move between GPU and system memory."),

"model.memory_budget_gib": dict(severity="caution",
  what="How much GPU memory this application is allowed to reserve. It also decides how large the decoder's chunks are.",
  more="A larger budget allows longer songs and faster whole-song decoding.",
  less="A smaller budget leaves room for other programs using the same GPU.",
  recommended="24 is the documented baseline. 40 suits a 48 GB card that is not shared.",
  extremes="Setting it near the card's total leaves nothing for other processes; setting it very low forces small decoder chunks and slow decoding.",
  cost="Directly caps VRAM; too low a value causes out-of-memory failures on long songs."),

"model.local_files_only": dict(severity="info",
  what="Forbids the application from contacting Hugging Face while generating. Everything must already be on disk.",
  recommended="On. It makes runs deterministic and keeps the machine offline.",
  extremes="With it off and a model that is not downloaded yet, the first run stalls while several gigabytes are fetched.",
  cost="None when the weights are already local."),

"planner.temperature": dict(severity="info",
  what="How adventurous the model is while writing the score, before any audio exists.",
  more="Higher values produce more unusual melodies and chord choices.",
  less="Lower values produce conventional, predictable composition.",
  recommended="0.7. The planner is deliberately steadier than the audio stage.",
  extremes="Above about 1.5 the score often stops making musical sense, which then spoils the audio built on it.",
  cost="None."),

"planner.top_p": dict(severity="info",
  what="Limits the planner's choices to the most likely options that together account for this share of the probability.",
  more="Closer to 1 allows rarer musical ideas.",
  less="Lower values keep the composition safe and repetitive.",
  recommended="0.9.",
  cost="None."),

"planner.top_k": dict(severity="info",
  what="A hard cap on how many candidate notes or chords the planner weighs at each step.",
  more="Higher values widen the pool and add variety.",
  less="Lower values narrow it toward the single most obvious choice.",
  recommended="30.",
  extremes="A value of 1 makes the planner fully deterministic and usually dull.",
  cost="None."),

"planner.repetition_penalty": dict(severity="caution",
  what="Discourages the planner from writing the same bars over and over.",
  more="Higher values push harder against repeated material.",
  less="Lower values allow more repetition.",
  recommended="1.005, which is almost neutral on purpose — real songs repeat their sections, and penalising that hurts structure.",
  extremes="Values much above 1.05 tend to destroy verse and chorus repetition, producing a score that wanders.",
  cost="None."),

"planner.penalty_window": dict(severity="info",
  what="How far back the repetition penalty looks when deciding whether something is a repeat.",
  more="A larger window catches repetition across longer spans.",
  less="A smaller window only notices immediate repeats.",
  recommended="100.",
  cost="None."),

"planner.min_tokens": dict(severity="info",
  what="A floor that stops the planner from ending the score almost immediately.",
  more="Higher values force a longer composition.",
  less="Lower values let the planner stop early.",
  recommended="32.",
  cost="None."),

"planner.max_tokens": dict(severity="caution",
  what="The longest score the planner may write. It is a ceiling, not a target.",
  more="A higher ceiling allows longer and more detailed compositions.",
  less="A lower ceiling cuts the score off, and a truncated score usually means the song ends abruptly.",
  recommended="4096.",
  extremes="If the planner reaches this limit the result is marked truncated and the warning says so; it does not fail.",
  cost="A longer score adds planning time before audio generation starts."),

"planner.seed": dict(severity="info",
  what="A separate random seed for the planning stage. This exists in the ComfyUI workflow only.",
  recommended="Not applicable here. The native runtime derives both the score and the audio from the single Seed below, so there is nothing separate to set.",
  cost="Not applied by this backend."),

"sampling.seed": dict(severity="info",
  what="The starting point for every random choice in a run. The same seed with the same settings and the same weights reproduces the same song.",
  more="Any different number gives a completely different take on the same brief.",
  recommended="Keep a seed you like, and change one setting at a time to hear what that setting does.",
  cost="None."),

"sampling.control_after_generate": dict(severity="info",
  what="What happens to the seed after a run. Fixed reuses it, Randomize draws a fresh one on the server, Increment adds one.",
  recommended="Randomize while you are exploring, then switch to Fixed once you find a take worth refining.",
  extremes="The seed actually used is always saved to the manifest, so a randomised take is never lost.",
  cost="None."),

"sampling.temperature": dict(severity="caution",
  what="How adventurous the model is while generating the audio itself. This is the main creativity dial.",
  more="Higher values give more variation and surprise, and less stability.",
  less="Lower values give consistent, conservative performances.",
  recommended="1.0.",
  extremes="Much above 1.5 the performance tends to drift, lose the beat, or produce noise. Near 0 it becomes flat and repetitive.",
  cost="None."),

"sampling.top_p": dict(severity="info",
  what="Keeps only the most likely sounds that together account for this share of the probability, and ignores the long tail.",
  more="Closer to 1 keeps rarer choices in play, adding variety and risk.",
  less="Lower values tighten the performance toward the safest option.",
  recommended="0.95.",
  cost="None."),

"sampling.top_k": dict(severity="info",
  what="A hard cap on how many candidate sounds the model weighs at each step.",
  more="Higher values widen the pool.",
  less="Lower values narrow it.",
  recommended="100. Top-p usually does the useful work; this is a backstop.",
  cost="None."),

"sampling.repetition_penalty": dict(severity="caution",
  what="Pushes the model away from looping the same musical material.",
  more="Higher values break loops more aggressively.",
  less="Lower values allow more repetition, which can turn into a stuck groove.",
  recommended="1.2.",
  extremes="Above roughly 1.5 the performance becomes restless and can lose its groove, because a steady beat is itself repetition.",
  cost="None."),

"sampling.penalty_window": dict(severity="info",
  what="How many recent moments the repetition penalty considers when judging a repeat.",
  more="A larger window notices repetition across longer stretches.",
  less="A smaller window only reacts to immediate loops.",
  recommended="50.",
  cost="None."),

"sampling.min_tokens": dict(severity="info",
  what="A floor on song length. Twenty-five units is one second, so 200 is about eight seconds.",
  more="Higher values stop the model from finishing too early.",
  less="Lower values let a short idea end when it wants to.",
  recommended="200.",
  cost="None."),

"sampling.max_duration_seconds": dict(severity="caution",
  what="The longest the song is allowed to be. The model stops when the song feels finished, so this is a ceiling rather than a target.",
  more="A higher ceiling lets a long song finish instead of being cut off.",
  less="A lower ceiling keeps runs short while you are experimenting.",
  recommended="Two to three minutes for a full song; 30 to 60 seconds while trying ideas.",
  extremes="If the model reaches the ceiling the result is marked truncated and may end abruptly. Long songs are also where GPU memory runs out.",
  cost="This is the single biggest influence on both generation time and VRAM. Roughly, time scales with the audio produced."),

"sampling.max_tokens_override": dict(severity="caution",
  what="Sets the length ceiling directly in model units instead of in seconds. Twenty-five units is one second of audio.",
  recommended="Leave empty and use Maximum duration, which is the same control in friendlier units.",
  extremes="A value here overrides the duration slider entirely, so the two can appear to disagree.",
  cost="Same as Maximum duration."),

"synthesis.cfg_scale": dict(severity="caution",
  what="How strongly the style, lyrics and score are allowed to steer the audio, as opposed to letting the model follow its own instincts.",
  more="Higher values follow your brief more literally, at the cost of naturalness.",
  less="Lower values give the model more freedom and a looser reading of the brief.",
  recommended="Leave empty to use the runtime default, which is 1.0 with a plan and 1.01 without one.",
  extremes="Large values tend to produce strained, over-constrained audio.",
  cost="Values other than 1.0 run a second guidance pass, which makes generation slower."),

"synthesis.ode_steps": dict(severity="caution",
  what="How many refinement steps are used to turn the model's internal representation into detailed audio. Think of it as how many passes the renderer makes.",
  more="More steps can give slightly cleaner detail.",
  less="Fewer steps are faster and rougher.",
  recommended="32, which is the validated setting. Gains above it are small.",
  extremes="Very low values produce audible artefacts.",
  cost="Time scales almost linearly with this number; doubling it roughly doubles the synthesis stage."),

"synthesis.ode_method": dict(severity="info",
  what="The mathematical recipe used to take each refinement step. Different recipes trade accuracy against the number of steps needed; this runtime is built and validated around one of them.",
  recommended="Fixed by the runtime. It cannot be changed at this context length, and is shown so the synthesis settings are complete.",
  cost="None."),

"synthesis.sampler_name": dict(severity="info",
  what="In ComfyUI, the algorithm that walks from noise to a finished result. Different samplers take different paths and sound slightly different.",
  recommended="Not applicable here. This runtime uses one fixed solver, so there is no sampler list to choose from; use Synthesis steps instead.",
  cost="Not applied by this backend."),

"synthesis.scheduler": dict(severity="info",
  what="In ComfyUI, how the refinement steps are spaced out — evenly, or concentrated at one end.",
  recommended="Not applicable here. The spacing is uniform and not configurable.",
  cost="Not applied by this backend."),

"synthesis.denoise": dict(severity="info",
  what="In ComfyUI, how much of the existing content is replaced rather than kept, which is how image-to-image style workflows work.",
  recommended="Not applicable here. This runtime always renders the full trajectory, so there is no partial-refinement entry point.",
  cost="Not applied by this backend."),

"synthesis.seconds": dict(severity="info",
  what="In ComfyUI, the length of the empty audio canvas reserved before generation begins, which fixes the maximum length of the result.",
  recommended="Not applicable here. This runtime sizes its canvas from the audio the model actually produced. Use Maximum duration.",
  cost="Not applied by this backend."),

"synthesis.batch_size": dict(severity="info",
  what="In ComfyUI, how many separate results a single run produces, so several variations come back together.",
  recommended="Not applicable here. One run produces one song; queue several runs to compare takes.",
  cost="Not applied by this backend."),

"decoder.mode": dict(severity="caution",
  what="How the finished song is turned into an audio file: all at once, or in chunks that are stitched together.",
  more="Whole-song decoding is faster when there is enough free GPU memory.",
  less="Tiled decoding uses a predictable, much smaller amount of memory and works at any length.",
  recommended="Tiled. It is the safe choice and the speed difference is small.",
  extremes="Whole-song decoding of a long track is the most common cause of out-of-memory failures.",
  cost="Whole-song is faster but its memory use grows with song length."),

"decoder.tile_frames": dict(severity="caution",
  what="How much audio the tiled decoder handles per chunk. Twenty-five frames is one second.",
  more="Larger chunks decode faster and use more memory.",
  less="Smaller chunks use less memory and take longer.",
  recommended="1024, or 512 if you are sharing the GPU.",
  extremes="Very small tiles make decoding noticeably slow; very large ones defeat the purpose of tiling.",
  cost="Directly trades decoding time against VRAM."),

"decoder.halo_frames": dict(severity="info",
  what="A little extra audio decoded either side of each chunk and then trimmed off, so the joins between chunks are inaudible.",
  recommended="Fixed by the runtime. It is shown so the decoder settings are complete, not because you need to change it.",
  cost="None."),

"output.format": dict(severity="info",
  what="The file you get. FLAC and WAV are lossless and are written directly by the model runtime. MP3 is smaller and is converted from the lossless file afterwards.",
  recommended="FLAC. It is lossless, widely supported and about half the size of WAV.",
  extremes="MP3 loses a little quality by design, and requires FFmpeg to be installed. The lossless master is always kept alongside it.",
  cost="MP3 adds a second or two of conversion after generation."),

"output.filename_prefix": dict(severity="info",
  what="The start of the filename when you download a song. Files on disk are named from internal ids and are unaffected.",
  recommended="Anything recognisable, such as a project name.",
  cost="None."),

"output.keep_canonical": dict(severity="info",
  what="Keeps the model's own untouched output alongside any converted copy, so nothing you generate is ever only available in a lossy format.",
  recommended="Always on; it is not something you should need to turn off.",
  cost="A little extra disk space."),
}


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    # The default-model option needs a non-empty value: a select control cannot
    # carry an empty option value, and an explicit sentinel is clearer anyway.
    for parameter in registry["parameters"]:
        if parameter["key"] == "model.checkpoint":
            parameter["default"] = "default"

    # Cover's reference audio is an input, like style and lyrics, so it belongs
    # in the registry rather than being special-cased in the frontend.
    if not any(p["key"] == "prompt.reference_upload_id" for p in registry["parameters"]):
        index = next(i for i, p in enumerate(registry["parameters"]) if p["key"] == "prompt.abc")
        registry["parameters"].insert(index + 1, {
            "key": "prompt.reference_upload_id",
            "label": "Reference audio",
            "group": "prompt",
            "type": "upload",
            "default": None,
            "kind": "model",
            "advanced": False,
            "requires_mode": ["cover"],
            "capability": "cover",
            "help": "The recording a cover is based on. It is transcribed to a melody score, which then guides generation.",
            "native": {"supported": True, "path": "SheetSage2 -> request.abc",
                       "note": "Transcribed by the SheetSage2 service, then supplied to YuE2 as the planner input."},
            "comfy": {"node": "LoadAudio", "widget": "audio",
                      "note": "The workflow reads a file from ComfyUI's input directory; the studio uses an upload."},
        })

    missing = []
    for parameter in registry["parameters"]:
        guidance = G.get(parameter["key"])
        if guidance is None:
            missing.append(parameter["key"])
            continue
        parameter["guidance"] = {k: v for k, v in guidance.items() if v}

    registry["registry_version"] = "2026-09-16"
    REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"parameters: {len(registry['parameters'])}, with guidance: {len(registry['parameters']) - len(missing)}")
    if missing:
        print("MISSING GUIDANCE:", missing)
        return 1
    caution = [p["key"] for p in registry["parameters"] if p["guidance"]["severity"] == "caution"]
    print(f"caution: {len(caution)} / info: {len(registry['parameters']) - len(caution)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
