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
from pathlib import Path
from typing import Any

import numpy as np
from yue2_studio_core.abc import score_duration_seconds
from yue2_studio_core.budget import estimate_budget, load_model_limits, resolve_effective_tokens
from yue2_studio_core.constants import LATENT_FRAME_RATE
from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.models import GenerationConfig, GenerationMode, JobStatus
from yue2_studio_core.settings import Settings

from yue2_studio_core.store import Store

from ..model_manager.manager import ModelManager
from .transcription import SheetSage2Transcriber
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
        # Truncation is reported by the worker, which knows the budget, the
        # tokens actually generated and what to do about it. A second, vaguer
        # line here would only bury that.
        return None


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

    def __init__(
        self,
        settings: Settings,
        manager: ModelManager | None = None,
        store: Store | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or Store(settings)
        self.manager = manager or ModelManager(settings, store=self.store)
        self.transcriber = SheetSage2Transcriber(settings)
        self._pipeline: Any = None
        self._request: Any = None
        self._effective_config: dict | None = None
        self._planner_sampling: Any = None
        self._semantic_sampling: Any = None
        self._budget: dict[str, Any] = {}
        self._adjustments: list[dict[str, Any]] = []
        self._termination: str | None = None

    # -- capabilities ------------------------------------------------------ #

    async def get_capabilities(self) -> dict:
        state = self.manager.state()
        cover_ok, cover_reason = self.transcriber.available()
        modes = ["full", "melody", "off", "score_edit"] + (["cover"] if cover_ok else [])
        return {
            "backend": self.name,
            "modes": modes,
            "model": state,
            "cover": {"supported": cover_ok, "reason": cover_reason},
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
            available, reason = self.transcriber.available()
            if not available:
                raise StudioError(
                    ErrorCode.UNSUPPORTED_CAPABILITY,
                    reason or "The cover workflow needs the SheetSage2 transcription service.",
                    stage="validation",
                )
            if not config.prompt.reference_upload_id:
                raise StudioError(
                    ErrorCode.AUDIO_INPUT_ERROR,
                    "Cover mode needs a reference recording to transcribe.",
                    stage="validation",
                )
            warnings.append(
                "The melody is transcribed from your reference. Transcription is an estimate, and its "
                "mistakes carry into the cover — review the score afterwards."
            )
        await asyncio.to_thread(self.manager.verify_files, config)
        return warnings

    # -- stages ------------------------------------------------------------ #

    async def _transcribe_reference(self, config: GenerationConfig, context: GenerationContext) -> str:
        """Turn the reference recording into a melody score.

        Runs before the YuE2 weights are loaded so the two models are not
        resident on the same card at the same time.
        """
        upload = self.store.get_upload(config.prompt.reference_upload_id or "")
        audio_path = self.store.absolute(upload.path)
        output_dir = self.store.generation_dir(
            self.store.get_job(context.job_id).project_id, context.job_id
        ) / "score" / "transcription"

        context.reporter.begin(
            JobStatus.TRANSCRIBING, "transcribing", "Transcribing reference audio", unit="windows"
        )

        def _run():
            return self.transcriber.transcribe(
                audio_path,
                output_dir,
                device_index=self.manager.device_index,
                cancelled=context.cancelled,
                on_progress=lambda completed, total: context.reporter.update(completed, total=total),
            )

        result = await asyncio.to_thread(_run)
        for warning in result.warnings:
            context.reporter.note(f"Transcription: {warning}", severity="WARNING")
        context.reporter.note(
            f"Transcribed {result.duration_seconds:.0f}s of reference audio in "
            f"{result.elapsed_seconds:.0f}s."
            if result.duration_seconds and result.elapsed_seconds
            else "Reference audio transcribed."
        )
        return result.abc

    async def prepare(self, config: GenerationConfig, context: GenerationContext) -> None:
        # The adapter outlives a job, so anything recorded per run is cleared
        # here. Carrying one job's adjustments into the next would put a change
        # in a manifest that never happened.
        self._budget = {}
        self._adjustments = []
        self._termination = None

        transcribed_abc: str | None = None
        if config.prompt.mode is GenerationMode.COVER:
            transcribed_abc = await self._transcribe_reference(config, context)

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
        # A cover's score comes from the transcription; every other mode uses
        # whatever score the request carried, if any.
        score = transcribed_abc if transcribed_abc is not None else config.prompt.abc
        self._request = SongRequest(
            style=config.prompt.style,
            lyrics=config.prompt.lyrics,
            cot=config.prompt.mode.cot,
            seed=config.sampling.seed,
            abc=(score or "").strip() or None,
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

    def _resolve_token_budget(self, context: GenerationContext, plan: PlanResult) -> Any:
        """Decide the acoustic token budget now that the score is written.

        The model is not told how long to make a song: it writes what the style,
        lyrics and score imply, and emits its end token when that is finished.
        The duration limit is therefore a hard stop, not a target, and a limit
        below the written length cuts the song off part way — which is exactly
        the truncation this addresses.

        The written score states its own length, so once planning is done the
        required budget is known before a single audio token is generated. This
        either raises the limit to let the song finish, or refuses now rather
        than spending minutes producing a fragment.

        Raising the limit never makes a song longer than it was going to be; it
        only stops it being cut short. The cost is a proportionally larger
        key/value cache, which is reported.
        """
        from yue2.protocol import Sampling

        config = context.config
        limits = load_model_limits(
            str(self.settings.configs_path),
            self.manager.resolve_model(config),
            self.manager.resolve_vae(config),
        )
        merge_file = Path(self.manager.resolve_model(config)) / "qwen.tiktoken"
        planned_seconds = score_duration_seconds(plan.abc) if plan.abc else None
        guidance = self._request.guidance if self._request is not None else 1.0

        estimate = estimate_budget(
            limits=limits,
            cot=config.prompt.mode.cot,
            style=config.prompt.style,
            lyrics=config.prompt.lyrics,
            requested_seconds=config.sampling.effective_duration_seconds,
            # The score now exists, so its real cost replaces the reservation.
            abc=plan.abc or "",
            planner_max_tokens=config.planner.max_tokens,
            merge_file=str(merge_file) if merge_file.is_file() else None,
            planned_seconds=planned_seconds,
            cfg_branches=1 if guidance == 1 else 2,
        )

        requested = self._semantic_sampling.max_tokens
        decision = resolve_effective_tokens(
            limits=limits,
            estimate=estimate,
            requested_tokens=requested,
            fit_to_plan=config.sampling.fit_to_plan,
        )

        if not decision.allowed:
            refusal = decision.refusal or {}
            raise StudioError(
                ErrorCode[refusal.get("code", "TOKEN_BUDGET_EXCEEDED")],
                refusal.get("message", "The request does not fit the model's token budget."),
                stage="planning",
                details={"budget": estimate.to_dict()},
            )

        effective = decision.effective_tokens
        if decision.adjustment:
            self._adjustments.append(decision.adjustment)
            context.reporter.note(
                f"The planned song runs {planned_seconds:.0f} s, longer than the "
                f"{decision.adjustment['requested']:.0f} s limit. The limit was raised to "
                f"{decision.adjustment['effective']:.0f} s so the song can finish.",
                severity="WARNING",
            )

        estimate_dict = estimate.to_dict()
        estimate_dict["effective_tokens"] = effective
        estimate_dict["effective_seconds"] = round(limits.tokens_to_seconds(effective), 1)
        self._budget["plan"] = estimate_dict
        self._budget["limits"] = limits.to_dict()

        if effective == requested:
            return self._semantic_sampling
        return Sampling(
            temperature=self._semantic_sampling.temperature,
            top_p=self._semantic_sampling.top_p,
            top_k=self._semantic_sampling.top_k,
            repetition_penalty=self._semantic_sampling.repetition_penalty,
            penalty_window=self._semantic_sampling.penalty_window,
            min_tokens=min(self._semantic_sampling.min_tokens, effective),
            max_tokens=effective,
        )

    async def generate_audio(self, context: GenerationContext, plan: PlanResult) -> AudioTokensResult:
        pipeline = self._pipeline
        sampling = await asyncio.to_thread(self._resolve_token_budget, context, plan)
        semantic_started = time.perf_counter()

        def _semantic():
            return pipeline.generate_semantic(
                plan.handle,
                sampling=sampling,
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

        # The runtime reports truncated when it stopped at the ceiling instead
        # of emitting its end token. That distinction is the whole difference
        # between a finished song and a fragment, so it is recorded explicitly.
        self._termination = "MAX_TOKENS" if semantic.truncated else "EOS"
        self._budget["semantic"] = {
            "budget_tokens": sampling.max_tokens,
            "tokens_generated": len(semantic.tokens),
            "termination_reason": self._termination,
        }

        # One codec token becomes exactly one latent frame. If that ever stops
        # holding, the decoder would be fed a misaligned sequence, so it is
        # checked rather than assumed.
        if latents.shape[0] != len(semantic.tokens):
            raise StudioError(
                ErrorCode.DECODER_FAILED,
                f"The acoustic stage produced {len(semantic.tokens):,} tokens but "
                f"{latents.shape[0]:,} latent frames. Refusing to decode a misaligned sequence.",
                stage="synthesis",
            )

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
        effective["token_budget"] = dict(self._budget)
        effective["termination_reason"] = self._termination
        if self._adjustments:
            effective["adjustments"] = list(self._adjustments)
        return BackendResult(
            plan=plan,
            tokens=tokens,
            audio=audio,
            effective_config=effective,
            weights=weights,
            runtime=runtime,
            request_identity=request_identity,
            semantic_tokens=semantic_tokens,
            budget=dict(self._budget),
            termination_reason=self._termination,
            adjustments=list(self._adjustments),
        )

    async def cancel(self, job_id: str) -> None:
        """Cancellation is cooperative; the running stage checks the flag."""
        logger.info("cancellation requested for %s", job_id)

    async def shutdown(self) -> None:
        await asyncio.to_thread(self.manager.release)
