"""Writing a generation's artifacts and its manifest.

The model's own output is the canonical file and is never re-encoded. An MP3,
when asked for, is an additional delivery file produced by FFmpeg from that
canonical file.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile
from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.ids import new_id
from yue2_studio_core.manifest import build_manifest
from yue2_studio_core.models import ArtifactRef, GenerationJob, Score
from yue2_studio_core.store import Store, write_json_atomic, write_text_atomic

logger = logging.getLogger(__name__)

_SUBTYPES = {".flac": "PCM_24", ".wav": "FLOAT"}


def _record(store: Store, kind: str, path: Path, **extra) -> ArtifactRef:
    from yue2_studio_core.store import sha256_file

    return ArtifactRef(
        kind=kind,
        path=store.relative(path),
        bytes=path.stat().st_size,
        sha256=sha256_file(path),
        **extra,
    )


def apply_incomplete_fade(audio: np.ndarray, sample_rate: int, milliseconds: int) -> tuple[np.ndarray, dict | None]:
    """Fade out audio that was cut off mid-phrase.

    A generation stopped at its token ceiling ends on an arbitrary sample, and
    a hard cut there is an audible click on top of an already abrupt ending.
    A short fade removes the click without pretending the song finished.

    Applied only to an incomplete take, never to one that reached its own
    ending, and always recorded in the manifest so the audio is never quietly
    altered.
    """
    if milliseconds <= 0 or audio.size == 0:
        return audio, None
    samples = min(int(sample_rate * milliseconds / 1000), audio.shape[0])
    if samples < 2:
        return audio, None
    ramp = np.linspace(1.0, 0.0, samples, dtype=np.float32)
    faded = audio.astype(np.float32, copy=True)
    if faded.ndim == 1:
        faded[-samples:] *= ramp
    else:
        faded[-samples:, :] *= ramp[:, None]
    return faded, {
        "applied": "fade_out",
        "milliseconds": milliseconds,
        "samples": samples,
        "reason": "the take was cut off at its token limit; the fade removes the cut's click",
    }


def write_audio(store: Store, directory: Path, audio: np.ndarray, sample_rate: int, output_format: str) -> list[ArtifactRef]:
    """Write the canonical audio, plus an MP3 delivery copy when requested."""
    canonical_suffix = ".wav" if output_format == "wav" else ".flac"
    canonical = directory / "audio" / f"final{canonical_suffix}"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    try:
        soundfile.write(canonical, audio, sample_rate, subtype=_SUBTYPES[canonical_suffix])
    except Exception as exc:
        raise StudioError(ErrorCode.ARTIFACT_WRITE_FAILED, str(exc), stage="post_processing") from exc

    channels = 1 if audio.ndim == 1 else audio.shape[1]
    duration = audio.shape[0] / sample_rate
    artifacts = [
        _record(
            store,
            "audio",
            canonical,
            content_type="audio/flac" if canonical_suffix == ".flac" else "audio/wav",
            duration_seconds=duration,
            sample_rate=sample_rate,
            channels=channels,
        )
    ]

    if output_format == "mp3":
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise StudioError(
                ErrorCode.ARTIFACT_WRITE_FAILED,
                "MP3 delivery was requested but FFmpeg is not on PATH.",
                stage="post_processing",
            )
        delivery = directory / "audio" / "final.mp3"
        # No shell string: the arguments are passed as a list.
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(canonical), "-codec:a", "libmp3lame", "-q:a", "2", str(delivery)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not delivery.is_file():
            raise StudioError(
                ErrorCode.ARTIFACT_WRITE_FAILED,
                f"FFmpeg could not write the MP3: {result.stderr.strip()[-400:]}",
                stage="post_processing",
            )
        artifacts.append(
            _record(
                store,
                "delivery",
                delivery,
                content_type="audio/mpeg",
                duration_seconds=duration,
                sample_rate=sample_rate,
                channels=channels,
            )
        )
    return artifacts


def write_intermediates(
    store: Store,
    directory: Path,
    *,
    latents: np.ndarray | None,
    semantic_tokens: np.ndarray | None,
) -> list[ArtifactRef]:
    artifacts: list[ArtifactRef] = []
    intermediates = directory / "intermediates"
    intermediates.mkdir(parents=True, exist_ok=True)
    if latents is not None and latents.size:
        path = intermediates / "latent.npy"
        np.save(path, latents.astype(np.float32))
        artifacts.append(_record(store, "latent", path, content_type="application/octet-stream"))
    if semantic_tokens is not None and semantic_tokens.size:
        path = intermediates / "semantic.npy"
        np.save(path, semantic_tokens.astype(np.int32))
        artifacts.append(_record(store, "semantic", path, content_type="application/octet-stream"))
    return artifacts


def write_score(store: Store, job: GenerationJob, abc: str | None) -> tuple[Score | None, list[ArtifactRef]]:
    if not abc:
        return None, []
    score = Score(
        id=new_id("scr"),
        generation_id=job.id,
        project_id=job.project_id,
        source_abc=abc,
        origin="planner" if not job.config.prompt.abc.strip() else "manual",
    )
    store.save_score(score)
    path = store.generation_dir(job.project_id, job.id) / "score" / "source.abc"
    return score, [_record(store, "score", path, content_type="text/vnd.abc")]


def write_configs(store: Store, directory: Path, job: GenerationJob, effective_config: dict) -> list[ArtifactRef]:
    request_path = directory / "request.json"
    write_text_atomic(request_path, job.config.model_dump_json(indent=2))
    effective_path = directory / "effective_config.json"
    write_json_atomic(effective_path, effective_config)
    return [
        _record(store, "config", request_path, content_type="application/json"),
        _record(store, "config", effective_path, content_type="application/json"),
    ]


def write_manifest(
    store: Store,
    directory: Path,
    job: GenerationJob,
    *,
    runtime: dict,
    weights: dict,
    effective_config: dict,
    hardware: dict,
) -> ArtifactRef:
    manifest = build_manifest(
        job,
        runtime=runtime,
        weights=weights,
        effective_config=effective_config,
        hardware=hardware,
        artifacts=[artifact.model_dump(mode="json") for artifact in job.artifacts],
        warnings=job.warnings,
    )
    path = directory / "manifest.json"
    write_json_atomic(path, manifest)
    logger.info("manifest written", extra={"generation_id": job.id})
    return _record(store, "manifest", path, content_type="application/json")


def write_failure(directory: Path, payload: dict) -> None:
    write_json_atomic(directory / "failure.json", json.loads(json.dumps(payload, default=str)))
