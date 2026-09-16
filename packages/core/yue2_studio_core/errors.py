"""Error taxonomy shared by the API and the worker.

Every failure that reaches a job record carries one of these codes so the UI can
explain what happened without parsing free text. Codes are stable; messages are
not.
"""
from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    CUDA_OOM = "CUDA_OOM"
    INVALID_CONFIG = "INVALID_CONFIG"
    INVALID_ABC = "INVALID_ABC"
    AUDIO_INPUT_ERROR = "AUDIO_INPUT_ERROR"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    #: The acoustic stage hit its token ceiling before the song ended.
    INCOMPLETE_TOKEN_LIMIT = "INCOMPLETE_TOKEN_LIMIT"
    #: The request cannot fit in the model's context window at all.
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"
    DECODER_FAILED = "DECODER_FAILED"
    ARTIFACT_WRITE_FAILED = "ARTIFACT_WRITE_FAILED"
    CANCELLED = "CANCELLED"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


# Guidance is shown verbatim in the UI next to the failure. Keep it actionable
# and never suggest that the application silently retried with other settings.
GUIDANCE: dict[ErrorCode, str] = {
    ErrorCode.MODEL_NOT_FOUND: (
        "The configured model directory does not exist. Check YUE2_MODEL_PATH "
        "in .env, or run scripts/download_models.sh."
    ),
    ErrorCode.MODEL_LOAD_FAILED: (
        "The weights could not be loaded. Verify the files against "
        "weights_manifest.json and confirm the runtime versions on /system."
    ),
    ErrorCode.CUDA_OOM: (
        "The GPU ran out of memory at this stage. Your requested configuration "
        "was kept unchanged. Reduce maximum duration, lower the decoder tile "
        "size, enable AR offload, or lower the memory budget, then retry."
    ),
    ErrorCode.INVALID_CONFIG: "One or more parameters are outside the supported range.",
    ErrorCode.INVALID_ABC: "The supplied ABC score could not be used as a planner input.",
    ErrorCode.AUDIO_INPUT_ERROR: "The reference audio could not be read.",
    ErrorCode.INFERENCE_FAILED: "Generation failed inside the model runtime. See the job log.",
    ErrorCode.INCOMPLETE_TOKEN_LIMIT: (
        "The song did not reach its own ending before the duration limit was used up, so the audio "
        "stops part way through. Raise the maximum duration to at least the planned length, or "
        "shorten the lyrics so the model writes a shorter song."
    ),
    ErrorCode.TOKEN_BUDGET_EXCEEDED: (
        "The requested song does not fit in the model's context window alongside its style, lyrics "
        "and score. Reduce the maximum duration, or shorten the lyrics to free context."
    ),
    ErrorCode.DECODER_FAILED: "Audio decoding failed. Try the tiled decoder with a smaller tile.",
    ErrorCode.ARTIFACT_WRITE_FAILED: "Artifacts could not be written. Check disk space and permissions on DATA_DIR.",
    ErrorCode.CANCELLED: "The job was cancelled.",
    ErrorCode.UNSUPPORTED_CAPABILITY: "The active backend does not support this option.",
    ErrorCode.NOT_FOUND: "The requested resource does not exist.",
    ErrorCode.CONFLICT: "The requested transition is not valid for the current state.",
    ErrorCode.UNKNOWN: "An unexpected error occurred. See the job log.",
}


class StudioError(Exception):
    """Base error carrying a taxonomy code and the stage it occurred in."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        stage: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error_code": self.code.value,
            "error_message": self.message,
            "stage": self.stage,
            "guidance": GUIDANCE.get(self.code, ""),
            "details": self.details,
        }


class NotFoundError(StudioError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.NOT_FOUND, message)


class ConflictError(StudioError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.CONFLICT, message)


class ValidationError(StudioError):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(ErrorCode.INVALID_CONFIG, message, details=details)


class UnsupportedCapabilityError(StudioError):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(ErrorCode.UNSUPPORTED_CAPABILITY, message, details=details)


def classify_exception(exc: BaseException) -> ErrorCode:
    """Map a runtime exception onto the taxonomy without swallowing detail."""
    if isinstance(exc, StudioError):
        return exc.code
    if isinstance(exc, (InterruptedError, KeyboardInterrupt)):
        return ErrorCode.CANCELLED
    name = type(exc).__name__
    text = f"{name}: {exc}".lower()
    if "outofmemory" in name.lower() or "out of memory" in text or "cuda oom" in text:
        return ErrorCode.CUDA_OOM
    if isinstance(exc, FileNotFoundError):
        return ErrorCode.MODEL_NOT_FOUND
    if isinstance(exc, (PermissionError, OSError)) and "space" in text:
        return ErrorCode.ARTIFACT_WRITE_FAILED
    return ErrorCode.UNKNOWN
