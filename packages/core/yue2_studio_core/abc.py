"""ABC score validation and comparison.

Thin wrapper over the vendored upstream parser so the API, the worker and the
score editor all agree on what a valid YuE2 score is.
"""
from __future__ import annotations

import json
from typing import Any

from .errors import ErrorCode, StudioError
from .vendor import abc_tools


class AbcValidationError(StudioError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.INVALID_ABC, message, stage="score")


def _plain(value: Any) -> Any:
    """Make the parser's Fractions and tuples JSON-safe."""
    return json.loads(json.dumps(value, default=abc_tools.json_value))


def validate(text: str) -> dict:
    """Parse a score. Returns a report; raises AbcValidationError if unusable."""
    if not text.strip():
        raise AbcValidationError("the score is empty")
    try:
        return _plain(abc_tools.report(abc_tools.parse(text)))
    except abc_tools.AbcError as exc:
        raise AbcValidationError(str(exc)) from exc
    except (ValueError, KeyError, IndexError) as exc:
        raise AbcValidationError(f"could not parse the score: {exc}") from exc


def try_validate(text: str) -> tuple[bool, dict | None, str | None]:
    """Non-raising variant for places that want to report rather than fail."""
    try:
        return True, validate(text), None
    except AbcValidationError as exc:
        return False, None, exc.message


def score_duration_seconds(text: str) -> float | None:
    """How long the written score intends the song to be, in seconds.

    Derived from the score's own tempo, meter and bar count rather than from a
    guess: the parser reports ``nominal_duration_seconds`` for exactly this.
    Measured against completed generations on this machine it predicts the final
    audio length to within a few percent, which makes it a sound basis for
    deciding whether a song will fit in its token budget before the expensive
    acoustic stage runs.
    """
    if not text.strip():
        return None
    try:
        report = validate(text)
    except AbcValidationError:
        return None
    value = report.get("nominal_duration_seconds")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def compare(before: str, after: str, *, voices: str = "both", allow_tempo_change: bool = False) -> dict:
    """Check which musical invariants survived an edit.

    ``match: true`` means notes, timing, meter and tempo are unchanged; harmony
    is deliberately allowed to differ, which is what a reharmonisation edit is.
    """
    names = abc_tools.VOICES if voices == "both" else (voices,)
    try:
        return _plain(
            abc_tools.compare(
                abc_tools.parse(before),
                abc_tools.parse(after),
                names,
                allow_tempo_change,
            )
        )
    except abc_tools.AbcError as exc:
        raise AbcValidationError(str(exc)) from exc


def strip_chords(text: str, *, keep_voice: str = "both") -> str:
    """Remove chord symbols, optionally silencing one voice (melody-only input)."""
    try:
        return abc_tools.strip_chords(text, keep_voice)
    except abc_tools.AbcError as exc:
        raise AbcValidationError(str(exc)) from exc
