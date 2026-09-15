"""Reference-audio uploads for the cover workflow.

Only audio is accepted, the size is capped, the filename is sanitised and the
bytes are inspected before anything is stored.
"""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store

from app.core.deps import settings_provider, store_provider

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_SUFFIXES = {".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aiff", ".aif"}
ALLOWED_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/x-flac",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/aiff",
    "audio/x-aiff",
    "application/octet-stream",
}


def _probe_audio(payload: bytes) -> dict:
    """Read duration/rate/channels without re-encoding. MP3/M4A may not be
    readable by libsndfile, which is reported rather than guessed at."""
    try:
        import soundfile

        with soundfile.SoundFile(io.BytesIO(payload)) as handle:
            return {
                "duration_seconds": len(handle) / handle.samplerate,
                "sample_rate": handle.samplerate,
                "channels": handle.channels,
                "format": handle.format,
            }
    except Exception as exc:
        return {"duration_seconds": None, "sample_rate": None, "channels": None, "probe_error": str(exc)}


@router.post("", status_code=201)
async def create_upload(
    file: UploadFile = File(...),
    settings: Settings = Depends(settings_provider),
    store: Store = Depends(store_provider),
) -> dict:
    from pathlib import Path

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise StudioError(
            ErrorCode.AUDIO_INPUT_ERROR,
            f"Unsupported file type '{suffix or 'unknown'}'. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}.",
        )
    if file.content_type and file.content_type not in ALLOWED_TYPES:
        raise StudioError(ErrorCode.AUDIO_INPUT_ERROR, f"Unsupported content type '{file.content_type}'.")

    payload = await file.read(settings.max_upload_bytes + 1)
    if len(payload) > settings.max_upload_bytes:
        raise StudioError(
            ErrorCode.AUDIO_INPUT_ERROR,
            f"The file is larger than the {settings.max_upload_bytes // (1024 * 1024)} MB limit.",
        )
    if not payload:
        raise StudioError(ErrorCode.AUDIO_INPUT_ERROR, "The file is empty.")

    upload = store.save_upload(file.filename or f"reference{suffix}", payload, file.content_type or "audio/wav")
    probe = _probe_audio(payload)
    upload.duration_seconds = probe.get("duration_seconds")
    upload.sample_rate = probe.get("sample_rate")
    upload.channels = probe.get("channels")
    from yue2_studio_core.store import write_json_atomic

    write_json_atomic(store.uploads_dir / upload.id / "upload.json", upload.model_dump(mode="json"))
    return {"upload": upload.model_dump(mode="json"), "probe": probe}


@router.get("/{upload_id}")
def get_upload(upload_id: str, store: Store = Depends(store_provider)) -> dict:
    return store.get_upload(upload_id).model_dump(mode="json")


@router.get("/{upload_id}/audio")
def stream_upload(upload_id: str, store: Store = Depends(store_provider)) -> FileResponse:
    upload = store.get_upload(upload_id)
    return FileResponse(store.absolute(upload.path), media_type=upload.content_type)
