"""Shared domain, configuration and storage for YuE2 Music Studio."""
from .constants import (
    LATENT_FRAME_RATE,
    SAMPLE_RATE,
    seconds_to_tokens,
    tokens_to_seconds,
)
from .errors import ErrorCode, StudioError, ValidationError
from .models import GenerationConfig, GenerationJob, GenerationMode, JobStatus, SongProject
from .queue import FilesystemJobQueue, JobQueue
from .settings import Settings, get_settings
from .store import Store

__all__ = [
    "ErrorCode",
    "FilesystemJobQueue",
    "GenerationConfig",
    "GenerationJob",
    "GenerationMode",
    "JobQueue",
    "JobStatus",
    "LATENT_FRAME_RATE",
    "SAMPLE_RATE",
    "Settings",
    "SongProject",
    "Store",
    "StudioError",
    "ValidationError",
    "get_settings",
    "seconds_to_tokens",
    "tokens_to_seconds",
]
__version__ = "0.1.0"
