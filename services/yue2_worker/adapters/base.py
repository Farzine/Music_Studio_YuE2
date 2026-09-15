"""Backend interface.

Every inference backend implements this. The worker drives the four stages
explicitly rather than calling one opaque function, because stage boundaries
are what the progress UI, the cancellation checks and the timing metrics are
built on.

A backend must never quietly substitute a parameter it cannot honour: it either
applies the request as given or raises, and the reason reaches the user.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np
from yue2_studio_core.models import GenerationConfig, JobStatus


class ProgressReporter(Protocol):
    """How a backend reports what it is doing.

    ``total`` is only ever a real target. A generation limit is a ceiling, not
    a target, so token stages leave it None and the UI shows counts instead of
    a percentage.
    """

    def begin(self, status: JobStatus, stage: str, label: str, *, total: int | None = None, unit: str | None = None) -> None: ...

    def update(self, completed: int, *, total: int | None = None) -> None: ...

    def note(self, message: str, *, severity: str = "INFO") -> None: ...


@dataclass
class GenerationContext:
    """Per-job state handed to the backend."""

    job_id: str
    config: GenerationConfig
    reporter: ProgressReporter
    cancel_event: threading.Event

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()


@dataclass
class PlanResult:
    """Symbolic plan. ``handle`` carries the backend's own object forward."""

    abc: str | None
    abc_token_count: int
    truncated: bool
    timing: dict[str, Any] = field(default_factory=dict)
    handle: Any = None


@dataclass
class AudioTokensResult:
    """Acoustic tokens plus the latents synthesised from them."""

    latents: np.ndarray
    semantic_token_count: int
    truncated: bool
    timing: dict[str, Any] = field(default_factory=dict)
    handle: Any = None


@dataclass
class DecodedAudio:
    audio: np.ndarray
    sample_rate: int
    timing: dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendResult:
    """Everything the worker needs to write a reproducible generation."""

    plan: PlanResult
    tokens: AudioTokensResult
    audio: DecodedAudio
    effective_config: dict[str, Any]
    weights: dict[str, Any]
    runtime: dict[str, Any]
    request_identity: str
    semantic_tokens: np.ndarray | None = None


@runtime_checkable
class MusicGenerationBackend(Protocol):
    """Contract implemented by the native, mock and ComfyUI backends."""

    name: str

    async def get_capabilities(self) -> dict: ...

    async def validate_config(self, config: GenerationConfig) -> list[str]:
        """Return warnings, or raise for anything this backend cannot honour."""

    async def prepare(self, config: GenerationConfig, context: GenerationContext) -> None:
        """Load or reuse weights. Must not reload an already-resident model."""

    async def generate_plan(self, context: GenerationContext) -> PlanResult: ...

    async def generate_audio(self, context: GenerationContext, plan: PlanResult) -> AudioTokensResult: ...

    async def decode_audio(self, context: GenerationContext, tokens: AudioTokensResult) -> DecodedAudio: ...

    async def finalise(
        self, context: GenerationContext, plan: PlanResult, tokens: AudioTokensResult, audio: DecodedAudio
    ) -> BackendResult: ...

    async def cancel(self, job_id: str) -> None:
        """Cooperative: sets the flag the running stages check."""

    async def shutdown(self) -> None: ...
