"""Artifact listing, streaming and download.

Paths are always resolved through the store, which refuses anything outside
DATA_DIR, so a crafted path cannot escape the data directory.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from yue2_studio_core.errors import NotFoundError
from yue2_studio_core.store import Store

from app.core.deps import store_provider

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

_AUDIO_TYPES = {".flac": "audio/flac", ".wav": "audio/wav", ".mp3": "audio/mpeg"}


@router.get("/{generation_id}")
def list_artifacts(generation_id: str, store: Store = Depends(store_provider)) -> dict:
    job = store.get_job(generation_id)
    return {"items": [artifact.model_dump(mode="json") for artifact in job.artifacts]}


def _audio_path(store: Store, generation_id: str) -> tuple[Path, str]:
    job = store.get_job(generation_id)
    artifact = job.audio_artifact()
    if artifact is None:
        raise NotFoundError("This generation has no audio yet.")
    path = store.absolute(artifact.path)
    if not path.is_file():
        raise NotFoundError("The audio file is missing from disk.")
    return path, job.config.output.filename_prefix


@router.get("/{generation_id}/audio")
def stream_audio(generation_id: str, store: Store = Depends(store_provider)) -> FileResponse:
    """Serve the canonical audio. FileResponse honours Range requests, so the
    browser can seek without downloading the whole file."""
    path, _ = _audio_path(store, generation_id)
    media_type = _AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})


@router.get("/{generation_id}/download")
def download_audio(generation_id: str, store: Store = Depends(store_provider)) -> FileResponse:
    path, prefix = _audio_path(store, generation_id)
    media_type = _AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename=f"{prefix}-{generation_id}{path.suffix}",
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
