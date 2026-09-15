"""Native YuE2 runtime adapter — the primary backend.

The four stages of ``yue2.YuE2Pipeline`` are driven explicitly (plan,
generate_semantic, synthesize, decode) so the studio can report the stage it is
really in, check for cancellation at each boundary, and time each phase.

Progress integration
--------------------
The runtime routes every stage through ``YuE2Pipeline._status``, a context
manager that yields a progress handle. The pipeline is constructed with
``progress=False`` so nothing is written to stderr, then ``progress`` is turned
back on and ``_status`` is replaced with an instance-level implementation that
forwards to the studio's reporter. That is the single documented seam; no
runtime behaviour, RNG state or configuration is touched by it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

import numpy as np
from yue2_studio_core.constants import LATENT_FRAME_RATE
from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.models import GenerationConfig, GenerationMode, JobStatus
from yue2_studio_core.settings import Settings

from ..model_manager.manager import ModelManager
from .base import (
    AudioTokensResult,
    BackendResult,
    DecodedAudio,
    GenerationContext,
    PlanResult,
    ProgressReporter,
)

logger = logging.getLogger(__name__)

#: Runtime stage label -> (job status, stage key, human label).
STAGE_LABELS: dict[str, tuple[JobStatus, str, str]] = {
    "Verifying model files": (JobStatus.LOADING_MODEL, "verifying_model", "Verifying model files"),
    "Loading model": (JobStatus.LOADING_MODEL, "loading_model", "Loading model"),
    "Planning score": (JobStatus.PLANNING, "planning", "Planning composition"),
    "Using provided score": (JobStatus.PLANNING, "planning", "Reading the supplied score"),
    "Generating song": (JobStatus.GENERATING, "semantic", "Generating audio tokens"),
    "Synthesizing audio": (JobStatus.GENERATING, "synthesis", "Synthesising audio"),
    "Loading audio decoder": (JobStatus.DECODING, "loading_decoder", "Loading audio decoder"),
    "Decoding audio": (JobStatus.DECODING, "decoding", "Decoding audio"),
}


class _StageProxy:
    """Stands in for ``yue2.progress._Stage`` and forwards to the reporter.

    Implements the same surface the runtime uses: ``update``, ``set_total``,
    ``advance``, ``token`` and ``finish``.
    """

    def __init__(self, reporter: ProgressReporter, label: str, total: int | None, unit: str | None) -> None:
        self.reporter = reporter
        self.label = label
        self.total = total
        self.unit = unit
        self.completed = 0
        status, stage, friendly = STAGE_LABELS.get(label, (JobStatus.GENERATING, label.lower().replace(" ", "_"), label))
        self.status = status
        self.stage = stage
        self.friendly = friendly

    def __enter__(self) -> "_StageProxy":
        self.reporter.begin(self.status, self.stage, self.friendly, total=self.total, unit=self.unit)
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def update(self, completed: int, total: int | None = None) -> None:
        self.completed = int(completed)
        if total is not None:
            self.total = int(total)
        self.reporter.update(self.completed, total=self.total)

    def set_total(self, total: int | None) -> None:
        self.total = None if total is None else int(total)
        self.reporter.update(self.completed, total=self.total)

    def advance(self, count: int = 1) -> None:
        self.update(self.completed + count)

    def token(self, phase: str, token: int) -> None:
        self.advance()

    def finish(self, status: str = "completed") -> None:
        if status == "truncated":
            self.reporter.note(f"{self.friendly} stopped at its token limit.", severity="WARNING")


def _install_reporter(pipeline: Any, reporter: ProgressReporter) -> None:
    """Point the runtime's stage reporting at this job's reporter."""

    @contextlib.contextmanager
    def _status(label: str, *, total: int | None = None, unit: str | None = None):
        with _StageProxy(reporter, label, total, unit) as stage:
            yield stage

    pipeline.progress = True  # makes the runtime create its progress callbacks
    pipeline._status = _status  # noqa: SLF001 - documented integration seam


def _classify(exc: BaseException, stage: str) -> StudioError:
    if isinstance(exc, StudioError):
        return exc
    name = type(exc).__name__
    text = f"{name}: {exc}"
    if "OutOfMemory" in name or "out of memory" in text.lower():
        return StudioError(ErrorCode.CUDA_OOM, text, stage=stage)
    if isinstance(exc, (InterruptedError, KeyboardInterrupt)):
        return StudioError(ErrorCode.CANCELLED, "Cancelled.", stage=stage)
    if stage == "decoding":
        return StudioError(ErrorCode.DECODER_FAILED, text, stage=stage)
    return StudioError(ErrorCode.INFERENCE_FAILED, text, stage=stage)


class NativeYuE2Backend:
    """Primary backend: the YuE2 Python runtime on the local GPU."""

    name = "native"

    def __init__(self, settings: Settings, manager: ModelManager | None = None) -> None:
        self.settings = settings
        self.manager = manager or ModelManager(settings)
        self._pipeline: Any = None
        self._request: Any = None
        self._effective_config: dict | None = None
        self._planner_sampling: Any = None
        self._semantic_sampling: Any = None

    # -- capabilities ------------------------------------------------------ #

    async def get_capabilities(self) -> dict:
        state = self.manager.state()
        return {
            "backend": self.name,
            "modes": ["full", "melody", "off", "score_edit"],
            "model": state,
            "runtime": self.manager.runtime_versions(),
        }

    async def validate_config(self, config: GenerationConfig) -> list[str]:
        warnings: list[str] = []
        unsupported = config.comfy_only_fields_in_use
        if unsupported:
            raise StudioError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "These settings exist only in the ComfyUI workflow and have no native equivalent: "
                + ", ".join(sorted(unsupported)),
                stage="validation",
                details={"parameters": sorted(unsupported)},
            )
        if config.prompt.mode is GenerationMode.COVER:
            raise StudioError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "The cover workflow needs the SheetSage2 transcription service.",
                stage="validation",
            )
        await asyncio.to_thread(self.manager.verify_files, config)
        return warnings

    # -- stages ------------------------------------------------------------ #

    async def prepare(self, config: GenerationConfig, context: GenerationContext) -> None:
        def _load():
            pipeline, loaded_now = self.manager.acquire(config)
            _install_reporter(pipeline, context.reporter)
            return pipeline, loaded_now

        context.reporter.begin(JobStatus.LOADING_MODEL, "loading_model", "Loading model")
        try:
            pipeline, loaded_now = await asyncio.to_thread(_load)
        except Exception as exc:
            raise _classify(exc, "loading_model") from exc
        self._pipeline = pipeline
        if not loaded_now:
            context.reporter.note("Reusing the resident model.")

        from yue2.protocol import SongRequest

        # Sampling travels with the request. A resident pipeline must never
        # apply the previous job's token budget to this one.
        self._planner_sampling, self._semantic_sampling = self.manager.native_sampling(config)
        self._request = SongRequest(
            style=config.prompt.style,
            lyrics=config.prompt.lyrics,
            cot=config.prompt.mode.cot,
            seed=config.sampling.seed,
            abc=config.prompt.abc.strip() or None,
            cfg_scale=config.synthesis.cfg_scale,
            id=context.job_id,
        )
        self._effective_config = pipeline.effective_config(
            self._request, self._planner_sampling, self._semantic_sampling
        )

    async def generate_plan(self, context: GenerationContext) -> PlanResult:
        pipeline, request = self._pipeline, self._request
        started = time.perf_counter()

        def _plan():
            return pipeline.plan(
                request=request,
                abc_sampling=self._planner_sampling,
                cancelled=context.cancelled,
            )

        try:
            plan = await asyncio.to_thread(_plan)
        except Exception as exc:
            raise _classify(exc, "planning") from exc
        return PlanResult(
            abc=plan.abc,
            abc_token_count=len(plan.abc_ids),
            truncated=bool(plan.truncated),
            timing={**dict(plan.timing or {}), "wall_seconds": time.perf_counter() - started},
            handle=plan,
        )

    async def generate_audio(self, context: GenerationContext, plan: PlanResult) -> AudioTokensResult:
        pipeline = self._pipeline
        semantic_started = time.perf_counter()

        def _semantic():
            return pipeline.generate_semantic(
                plan.handle,
                sampling=self._semantic_sampling,
                cancelled=context.cancelled,
            )

        try:
            semantic = await asyncio.to_thread(_semantic)
        except Exception as exc:
            raise _classify(exc, "semantic") from exc
        semantic_seconds = time.perf_counter() - semantic_started

        if context.cancelled():
            raise StudioError(ErrorCode.CANCELLED, "Cancelled before synthesis.", stage="semantic")

        synthesis_started = time.perf_counter()

        def _synthesize():
            return pipeline.synthesize(semantic, cancelled=context.cancelled)

        try:
            latents = await asyncio.to_thread(_synthesize)
        except Exception as exc:
            raise _classify(exc, "synthesis") from exc

        return AudioTokensResult(
            latents=latents,
            semantic_token_count=len(semantic.tokens),
            truncated=bool(semantic.truncated),
            timing={
                **dict(semantic.timing or {}),
                "semantic_seconds": semantic_seconds,
                "synthesis_seconds": time.perf_counter() - synthesis_started,
            },
            handle=semantic,
        )

    async def decode_audio(self, context: GenerationContext, tokens: AudioTokensResult) -> DecodedAudio:
        pipeline = self._pipeline
        full = context.config.decoder.mode.value == "full"
        started = time.perf_counter()

        def _decode():
            return pipeline.decode(tokens.latents, full=full)

        try:
            audio = await asyncio.to_thread(_decode)
        except Exception as exc:
            raise _classify(exc, "decoding") from exc
        return DecodedAudio(
            audio=audio,
            sample_rate=48000,
            timing={"decode_seconds": time.perf_counter() - started},
        )

    async def finalise(
        self,
        context: GenerationContext,
        plan: PlanResult,
        tokens: AudioTokensResult,
        audio: DecodedAudio,
    ) -> BackendResult:
        from yue2.storage import identity

        pipeline = self._pipeline
        effective = self._effective_config or pipeline.effective_config(
            self._request, self._planner_sampling, self._semantic_sampling
        )
        weights = dict(pipeline.weights)
        request_identity = identity(
            {"request": self._request.to_dict(), "config": effective, "weights": weights}
        )
        semantic_tokens = np.asarray(tokens.handle.tokens, dtype=np.int32) if tokens.handle else None
        runtime = self.manager.runtime_versions()
        runtime["backend"] = self.name
        runtime["latent_frame_rate"] = LATENT_FRAME_RATE
        return BackendResult(
            plan=plan,
            tokens=tokens,
            audio=audio,
            effective_config=effective,
            weights=weights,
            runtime=runtime,
            request_identity=request_identity,
            semantic_tokens=semantic_tokens,
        )

    async def cancel(self, job_id: str) -> None:
        """Cancellation is cooperative; the running stage checks the flag."""
        logger.info("cancellation requested for %s", job_id)

    async def shutdown(self) -> None:
        await asyncio.to_thread(self.manager.release)
