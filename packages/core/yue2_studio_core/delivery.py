"""Download delivery: what the audio can be handed over as, and how.

The file the model produced is the master and is never touched. A download in
another format is a copy made by FFmpeg into a temporary directory, served
once and then removed.

Which formats exist here is not a matter of taste: a format is offered only
when the FFmpeg actually installed reports the encoder it needs. Nothing is
advertised that would then fail.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .errors import ErrorCode, StudioError

#: How long a converted file may sit in the temporary directory before a later
#: request sweeps it. Long enough for a slow browser to finish the download,
#: short enough that nothing accumulates.
TEMPORARY_FILE_TTL_SECONDS = 15 * 60

_FFMPEG_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class DeliveryFormat:
    """One downloadable format and the exact FFmpeg call that produces it."""

    id: str
    label: str
    extension: str
    mime: str
    lossless: bool
    #: Encoder FFmpeg must report for this format to be offered at all.
    encoder: str
    #: Everything after the input file. No shell string is ever built.
    arguments: tuple[str, ...]
    description: str


#: Ordered best-quality-first, which is also the order the picker shows.
FORMATS: tuple[DeliveryFormat, ...] = (
    DeliveryFormat(
        id="flac",
        label="FLAC",
        extension=".flac",
        mime="audio/flac",
        lossless=True,
        encoder="flac",
        arguments=("-c:a", "flac", "-compression_level", "5"),
        description="Lossless. Identical audio to the master, about half the size of WAV.",
    ),
    DeliveryFormat(
        id="wav",
        label="WAV",
        extension=".wav",
        mime="audio/wav",
        lossless=True,
        encoder="pcm_s24le",
        arguments=("-c:a", "pcm_s24le"),
        description="Lossless and uncompressed. The safest input for any editor, and the largest file.",
    ),
    DeliveryFormat(
        id="mp3",
        label="MP3",
        extension=".mp3",
        mime="audio/mpeg",
        lossless=False,
        encoder="libmp3lame",
        arguments=("-c:a", "libmp3lame", "-q:a", "2"),
        description="Lossy, around 190 kbps. Plays everywhere.",
    ),
    DeliveryFormat(
        id="m4a",
        label="M4A (AAC)",
        extension=".m4a",
        mime="audio/mp4",
        lossless=False,
        encoder="aac",
        arguments=("-c:a", "aac", "-b:a", "256k"),
        description="Lossy, 256 kbps. The usual choice on Apple devices.",
    ),
    DeliveryFormat(
        id="ogg",
        label="OGG Vorbis",
        extension=".ogg",
        mime="audio/ogg",
        lossless=False,
        encoder="libvorbis",
        arguments=("-c:a", "libvorbis", "-q:a", "6"),
        description="Lossy, open format. Good quality at a small size; not supported by every player.",
    ),
)

FORMATS_BY_ID = {item.id: item for item in FORMATS}

#: Extension of the master file mapped to the format id it already is, so that
#: format can be served straight from disk with no re-encoding at all.
_SOURCE_FORMAT_BY_SUFFIX = {".flac": "flac", ".wav": "wav", ".mp3": "mp3"}


def source_format_id(path: Path | str) -> str | None:
    return _SOURCE_FORMAT_BY_SUFFIX.get(Path(path).suffix.lower())


# --------------------------------------------------------------------------- #
# Probing
# --------------------------------------------------------------------------- #

_encoder_cache: dict[tuple[str, float], frozenset[str]] = {}


def available_encoders(ffmpeg: Path | str | None) -> frozenset[str]:
    """Encoder names this FFmpeg reports, or an empty set when it is absent.

    Cached against the binary's path and modification time, so replacing
    FFmpeg is picked up without a restart while the common case costs nothing.
    """
    if ffmpeg is None:
        return frozenset()
    binary = Path(ffmpeg)
    if not binary.is_file():
        return frozenset()
    try:
        key = (str(binary), binary.stat().st_mtime)
    except OSError:
        return frozenset()
    cached = _encoder_cache.get(key)
    if cached is not None:
        return cached
    try:
        result = subprocess.run(
            [str(binary), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    names: set[str] = set()
    for line in result.stdout.splitlines():
        # " A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3)"
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("A") and len(parts[0]) == 6:
            names.add(parts[1])
    frozen = frozenset(names)
    _encoder_cache[key] = frozen
    return frozen


def format_catalogue(*, ffmpeg: Path | str | None, source: Path | str | None = None) -> list[dict]:
    """Every format, each marked with whether this installation can produce it.

    An unsupported format is still listed with the reason it is unavailable,
    because the picker hides it and the System page explains it; a silent
    omission would leave the user wondering.
    """
    encoders = available_encoders(ffmpeg)
    native = source_format_id(source) if source is not None else None
    catalogue = []
    for item in FORMATS:
        is_source = item.id == native
        if is_source:
            supported, reason = True, None
        elif not encoders:
            supported, reason = False, "FFmpeg was not found, so conversion is unavailable."
        elif item.encoder not in encoders:
            supported, reason = False, f"This FFmpeg build has no {item.encoder} encoder."
        else:
            supported, reason = True, None
        catalogue.append(
            {
                "id": item.id,
                "label": item.label,
                "extension": item.extension,
                "mime": item.mime,
                "lossless": item.lossless,
                "description": item.description,
                "supported": supported,
                "reason": reason,
                #: True for the format the master is already in: served as-is,
                #: bit for bit, with no conversion step.
                "is_source": is_source,
                "encoder": item.encoder,
            }
        )
    return catalogue


# --------------------------------------------------------------------------- #
# Filenames
# --------------------------------------------------------------------------- #

#: Anything a filesystem, a browser or a shell could misread. Directory
#: separators are in here, which is what stops `../../etc/passwd`.
_FORBIDDEN = re.compile(r"[\\/:*?\"<>|\x00-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")
#: Reserved on Windows even with an extension, so a download would be rejected.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
MAX_FILENAME_STEM = 120
#: Control characters that stand in for a space rather than for nothing.
_CONTROL_AS_SPACE = "\t\n\r\v\f"


def _is_control(character: str) -> bool:
    return ord(character) < 32 or ord(character) == 127


def sanitise_download_name(name: str | None, *, fallback: str, extension: str) -> str:
    """Turn whatever the user typed into one safe filename ending in ``extension``.

    Path separators, control characters and leading dots are removed rather
    than escaped, so no input can point the download anywhere but at itself.
    An extension the user typed is dropped when it is the one being appended,
    which is what stops ``song.mp3.mp3``.
    """
    candidate = unicodedata.normalize("NFC", name or "")
    # A line break is spacing the user typed; every other control character is
    # noise that would end up invisible in a filename.
    candidate = "".join(
        " " if character in _CONTROL_AS_SPACE else "" if _is_control(character) else character
        for character in candidate
    )
    # Take the last segment: "a/b/c" is a name, not a path.
    candidate = candidate.replace("\\", "/").split("/")[-1]
    candidate = _WHITESPACE.sub(" ", _FORBIDDEN.sub("", candidate)).strip(" .")

    extension = extension.lower()
    known = {item.extension for item in FORMATS}
    stem, dot, suffix = candidate.rpartition(".")
    if dot and f".{suffix.lower()}" in known:
        # Only a real audio extension is stripped; "Mix v1.2" keeps its ".2".
        candidate = stem.strip(" .") or candidate

    if not candidate:
        candidate = _WHITESPACE.sub(" ", _FORBIDDEN.sub("", fallback)).strip(" .") or "audio"
    candidate = candidate[:MAX_FILENAME_STEM].strip(" .") or "audio"
    if candidate.lower() in _RESERVED:
        # Reserved on Windows even with an extension. Keep what was typed and
        # make it usable rather than replacing it with something unrelated.
        candidate = f"{candidate}-audio"
    return f"{candidate}{extension}"


# --------------------------------------------------------------------------- #
# Conversion
# --------------------------------------------------------------------------- #


def convert(
    *,
    ffmpeg: Path | str | None,
    source: Path,
    target: Path,
    format_id: str,
) -> Path:
    """Write ``source`` to ``target`` in ``format_id``. The source is untouched.

    Raises rather than returning a half-written file: a download that claims a
    format has to be that format.
    """
    item = FORMATS_BY_ID.get(format_id)
    if item is None:
        raise StudioError(
            ErrorCode.INVALID_CONFIG,
            f"'{format_id}' is not a format this studio can deliver.",
            details={"parameter": "format", "supported": [entry.id for entry in FORMATS]},
        )
    binary = Path(ffmpeg) if ffmpeg else None
    if binary is None or not binary.is_file():
        raise StudioError(
            ErrorCode.ARTIFACT_WRITE_FAILED,
            f"{item.label} needs FFmpeg to convert the audio, and FFmpeg was not found.",
            stage="download",
            details={"format": format_id},
        )
    if item.encoder not in available_encoders(binary):
        raise StudioError(
            ErrorCode.ARTIFACT_WRITE_FAILED,
            f"{item.label} is unavailable: this FFmpeg build has no {item.encoder} encoder.",
            stage="download",
            details={"format": format_id, "encoder": item.encoder},
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [str(binary), "-nostdin", "-y", "-i", str(source), "-vn", *item.arguments, str(target)],
            capture_output=True,
            text=True,
            check=False,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise StudioError(
            ErrorCode.ARTIFACT_WRITE_FAILED,
            f"Converting to {item.label} took longer than {_FFMPEG_TIMEOUT_SECONDS} seconds and was stopped.",
            stage="download",
            details={"format": format_id},
        ) from exc
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise StudioError(
            ErrorCode.ARTIFACT_WRITE_FAILED,
            f"FFmpeg could not be started: {exc}",
            stage="download",
            details={"format": format_id},
        ) from exc

    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise StudioError(
            ErrorCode.ARTIFACT_WRITE_FAILED,
            f"FFmpeg could not write the {item.label} file: {result.stderr.strip()[-400:] or 'no output'}",
            stage="download",
            details={"format": format_id},
        )
    return target


def sweep_temporary(directory: Path, *, ttl_seconds: int = TEMPORARY_FILE_TTL_SECONDS) -> int:
    """Delete converted files older than the TTL. Returns how many went.

    The per-request cleanup already removes each file once it has been sent;
    this catches the ones whose download was abandoned midway.
    """
    if not directory.is_dir():
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for path in directory.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def remove_quietly(path: Path) -> None:
    """Delete a served temporary file. A failure here must not fail the response."""
    try:
        os.unlink(path)
    except OSError:
        pass
