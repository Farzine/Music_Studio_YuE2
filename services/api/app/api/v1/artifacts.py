"""Artifact listing, streaming and download.

Paths are always resolved through the store, which refuses anything outside
DATA_DIR, so a crafted path cannot escape the data directory.
"""
from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from yue2_studio_core.delivery import (
    FORMATS_BY_ID,
    convert,
    format_catalogue,
    remove_quietly,
    sanitise_download_name,
    source_format_id,
    sweep_temporary,
)
from yue2_studio_core.errors import NotFoundError, ValidationError
from yue2_studio_core.models import GenerationJob
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store

from app.core.deps import settings_provider, store_provider

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

_AUDIO_TYPES = {".flac": "audio/flac", ".wav": "audio/wav", ".mp3": "audio/mpeg"}


@router.get("/{generation_id}")
def list_artifacts(generation_id: str, store: Store = Depends(store_provider)) -> dict:
    job = store.get_job(generation_id)
    return {"items": [artifact.model_dump(mode="json") for artifact in job.artifacts]}


def _audio(store: Store, generation_id: str) -> tuple[GenerationJob, Path]:
    job = store.get_job(generation_id)
    artifact = job.audio_artifact()
    if artifact is None:
        raise NotFoundError("This generation has no audio yet.")
    path = store.absolute(artifact.path)
    if not path.is_file():
        raise NotFoundError("The audio file is missing from disk.")
    return job, path


def _default_stem(job: GenerationJob) -> str:
    """The filename offered before the user types one of their own.

    Readable first — the title is what the user recognises — with the version
    appended so two takes of the same song do not land on the same name. An
    untitled take falls back to its id, which is always unique.
    """
    title = " ".join((job.title or "").split())
    if not title:
        return f"{job.config.output.filename_prefix}-{job.id}"
    return f"{job.config.output.filename_prefix}-{title}-v{job.version}"


@router.get("/{generation_id}/audio")
def stream_audio(generation_id: str, store: Store = Depends(store_provider)) -> FileResponse:
    """Serve the canonical audio. FileResponse honours Range requests, so the
    browser can seek without downloading the whole file."""
    _, path = _audio(store, generation_id)
    media_type = _AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})


@router.get("/{generation_id}/formats")
def download_formats(
    generation_id: str,
    store: Store = Depends(store_provider),
    settings: Settings = Depends(settings_provider),
) -> dict:
    """What this generation can actually be downloaded as.

    Support is decided by asking the installed FFmpeg which encoders it has,
    so a format is never offered that would fail when chosen.
    """
    job, path = _audio(store, generation_id)
    ffmpeg = settings.ffmpeg_path
    return {
        "generation_id": job.id,
        "source": {
            "format": source_format_id(path),
            "extension": path.suffix.lower(),
            "bytes": path.stat().st_size,
        },
        "default_filename": _default_stem(job),
        "ffmpeg": {"path": str(ffmpeg) if ffmpeg.is_file() else None, "present": ffmpeg.is_file()},
        "formats": format_catalogue(ffmpeg=ffmpeg, source=path),
    }


@router.get("/{generation_id}/download")
def download_audio(
    generation_id: str,
    format: str | None = Query(None, description="Delivery format id; the master's own format by default"),
    filename: str | None = Query(None, description="Filename the browser should save it as, without extension"),
    store: Store = Depends(store_provider),
    settings: Settings = Depends(settings_provider),
) -> FileResponse:
    """Download the audio, optionally converted and renamed.

    The master file is never modified. When a different format is asked for, a
    copy is made in the data directory's temporary area, served, and deleted as
    soon as the response finishes.
    """
    job, path = _audio(store, generation_id)
    native = source_format_id(path)
    chosen = (format or native or "flac").lower()

    item = FORMATS_BY_ID.get(chosen)
    if item is None:
        raise ValidationError(
            f"'{chosen}' is not a format this studio can deliver.",
            details={"parameter": "format", "supported": sorted(FORMATS_BY_ID)},
        )
    download_name = sanitise_download_name(
        filename, fallback=_default_stem(job), extension=item.extension
    )

    if chosen == native:
        # Already the right format: hand over the master itself, unchanged.
        return FileResponse(path, media_type=item.mime, filename=download_name)

    temporary_dir = store.root / "tmp" / "downloads"
    sweep_temporary(temporary_dir)
    target = temporary_dir / f"{job.id}-{uuid.uuid4().hex}{item.extension}"
    convert(ffmpeg=settings.ffmpeg_path, source=path, target=target, format_id=chosen)
    return FileResponse(
        target,
        media_type=item.mime,
        filename=download_name,
        background=BackgroundTask(remove_quietly, target),
    )


@router.get("/{generation_id}/file")
def artifact_file(
    generation_id: str,
    path: str = Query(..., description="Artifact path as recorded on the generation"),
    store: Store = Depends(store_provider),
) -> FileResponse:
    job = store.get_job(generation_id)
    known = {artifact.path for artifact in job.artifacts}
    if path not in known:
        raise NotFoundError("Unknown artifact for this generation.")
    resolved = store.absolute(path)
    if not resolved.is_file():
        raise NotFoundError("The artifact is missing from disk.")
    media_type = _AUDIO_TYPES.get(resolved.suffix.lower()) or mimetypes.guess_type(resolved.name)[0]
    return FileResponse(resolved, media_type=media_type or "application/octet-stream")
