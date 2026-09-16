"""Mock backend.

Runs the whole studio — queue, stages, cancellation, artifacts, manifest,
player, library — without a GPU or any model weights. It synthesises a simple
deterministic tone from the seed. It is never presented as a real generation:
the manifest records ``backend: mock`` and the capability document says so.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time

import numpy as np
from yue2_studio_core.abc import score_duration_seconds
from yue2_studio_core.budget import estimate_budget, load_model_limits, resolve_effective_tokens
from yue2_studio_core.constants import LATENT_FRAME_RATE, SAMPLE_RATE
from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.models import GenerationConfig, JobStatus
from yue2_studio_core.settings import Settings

from .base import (
    AudioTokensResult,
    BackendResult,
    DecodedAudio,
    GenerationContext,
    PlanResult,
)

# Valid in the narrow two-voice dialect YuE2 accepts: native X:1, blank T:,
# chord symbols on the Vocal voice only.
MOCK_ABC = """X:1
T:
M:4/4
L:1/16
Q:1/4=96
V: Vocal clef=treble name="Vocal Melody" snm="Vocal"
V: Ins clef=treble name="Ins Melody" snm="Inst."
K:C
% verse
V: Vocal
"C"c4e4g4e4|"F"f4a4c'4a4|"G"g4b4d'4b4|"C"c'16|
V: Ins
C4E4G4E4|F4A4c4A4|G4B4d4B4|C16|
"""


class MockBackend:
    name = "mock"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._config: GenerationConfig | None = None
        self._truncated = False
        self._termination: str | None = None
        self._budget: dict = {}
        self._adjustments: list[dict] = []

    async def get_capabilities(self) -> dict:
        return {
            "backend": self.name,
            "modes": ["full", "melody", "off", "score_edit"],
            "model": {"loaded": True, "model": "mock", "vae": "mock"},
            "runtime": {"backend": "mock"},
        }

    async def validate_config(self, config: GenerationConfig) -> list[str]:
        if config.comfy_only_fields_in_use:
            raise StudioError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "ComfyUI-only settings are not applied by the mock backend.",
                stage="validation",
            )
        return ["This is the mock backend: the audio is a generated tone, not a song."]

    async def prepare(self, config: GenerationConfig, context: GenerationContext) -> None:
        self._config = config
        self._budget = {}
        self._adjustments = []
        self._truncated = False
        self._termination = None
        context.reporter.begin(JobStatus.LOADING_MODEL, "loading_model", "Loading model")
        await asyncio.sleep(0.2)

    def _effective_tokens(
        self, context: GenerationContext, plan: PlanResult, planned: float | None
    ) -> int:
        """Apply the same plan-versus-limit decision the native backend does."""
        config = context.config
        limits = load_model_limits(str(self.settings.configs_path))
        estimate = estimate_budget(
            limits=limits,
            cot=config.prompt.mode.cot,
            style=config.prompt.style,
            lyrics=config.prompt.lyrics,
            requested_seconds=config.sampling.effective_duration_seconds,
            abc=plan.abc or "",
            planner_max_tokens=config.planner.max_tokens,
            planned_seconds=planned,
        )
        decision = resolve_effective_tokens(
            limits=limits,
            estimate=estimate,
            requested_tokens=config.sampling.max_tokens,
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
        self._budget = {
            "plan": {**estimate.to_dict(), "effective_tokens": decision.effective_tokens},
            "limits": limits.to_dict(),
        }
        if decision.adjustment and planned is not None:
            self._adjustments.append(decision.adjustment)
            context.reporter.note(
                f"The planned song runs {planned:.0f} s, longer than the "
                f"{decision.adjustment['requested']:.0f} s limit. The limit was raised to "
                f"{decision.adjustment['effective']:.0f} s so the song can finish.",
                severity="WARNING",
            )
        return decision.effective_tokens

    async def generate_plan(self, context: GenerationContext) -> PlanResult:
        started = time.perf_counter()
        context.reporter.begin(JobStatus.PLANNING, "planning", "Planning composition", unit="tokens")
        for step in range(1, 41):
            if context.cancelled():
                raise StudioError(ErrorCode.CANCELLED, "Cancelled while planning.", stage="planning")
            context.reporter.update(step * 8)
            await asyncio.sleep(0.01)
        use_abc = context.config.prompt.abc.strip() or MOCK_ABC
        return PlanResult(
            abc=None if context.config.prompt.mode.cot == "off" else use_abc,
            abc_token_count=len(use_abc.split()),
            truncated=False,
            timing={"wall_seconds": time.perf_counter() - started},
            handle=None,
        )

    async def generate_audio(self, context: GenerationContext, plan: PlanResult) -> AudioTokensResult:
        started = time.perf_counter()
        config = context.config
        # The mock song is exactly as long as the plan says, so the same
        # budget decision the native backend makes can be exercised here
        # without a GPU.
        # Direct Audio writes no score, so there is nothing to predict from and
        # the limit stands as given — the same position the native backend is in.
        planned = score_duration_seconds(plan.abc or "")
        wanted = int((planned or 20.0) * LATENT_FRAME_RATE)
        budget = self._effective_tokens(context, plan, planned)
        frames = min(budget, wanted)
        self._truncated = frames < wanted
        self._termination = "MAX_TOKENS" if self._truncated else "EOS"
        context.reporter.begin(JobStatus.GENERATING, "semantic", "Generating audio tokens", unit="tokens")
        for step in range(1, 51):
            if context.cancelled():
                raise StudioError(ErrorCode.CANCELLED, "Cancelled while generating.", stage="semantic")
            context.reporter.update(int(frames * step / 50))
            await asyncio.sleep(0.01)
        context.reporter.begin(
            JobStatus.GENERATING, "synthesis", "Synthesising audio", total=config.synthesis.ode_steps, unit="steps"
        )
        for step in range(1, config.synthesis.ode_steps + 1):
            if context.cancelled():
                raise StudioError(ErrorCode.CANCELLED, "Cancelled while synthesising.", stage="synthesis")
            context.reporter.update(step)
            await asyncio.sleep(0.005)
        rng = np.random.default_rng(config.sampling.seed)
        latents = rng.standard_normal((frames, 64)).astype(np.float32)
        return AudioTokensResult(
            latents=latents,
            semantic_token_count=frames,
            truncated=self._truncated,
            timing={"semantic_seconds": time.perf_counter() - started, "synthesis_seconds": 0.0},
            handle=None,
        )

    async def decode_audio(self, context: GenerationContext, tokens: AudioTokensResult) -> DecodedAudio:
        started = time.perf_counter()
        seconds = tokens.latents.shape[0] / LATENT_FRAME_RATE
        chunks = max(1, int(seconds))
        context.reporter.begin(JobStatus.DECODING, "decoding", "Decoding audio", total=chunks, unit="chunks")
        seed = context.config.sampling.seed
        root = 220.0 * (2 ** ((seed % 12) / 12.0))
        samples = int(seconds * SAMPLE_RATE)
        t = np.arange(samples, dtype=np.float32) / SAMPLE_RATE
        wave = np.zeros(samples, dtype=np.float32)
        for index, ratio in enumerate((1.0, 1.25, 1.5)):
            wave += (0.25 / (index + 1)) * np.sin(2 * math.pi * root * ratio * t)
        envelope = np.clip(np.minimum(t / 0.5, (seconds - t) / 0.5), 0.0, 1.0).astype(np.float32)
        wave = (wave * envelope).astype(np.float32)
        for chunk in range(1, chunks + 1):
            if context.cancelled():
                raise StudioError(ErrorCode.CANCELLED, "Cancelled while decoding.", stage="decoding")
            context.reporter.update(chunk)
            await asyncio.sleep(0.005)
        audio = np.stack([wave, wave], axis=1)
        return DecodedAudio(audio=audio, sample_rate=SAMPLE_RATE, timing={"decode_seconds": time.perf_counter() - started})

    async def finalise(self, context, plan, tokens, audio) -> BackendResult:
        config = context.config
        effective = {
            "backend": "mock",
            "generation": json.loads(config.model_dump_json()),
            "cot": config.prompt.mode.cot,
            "cfg_scale": config.synthesis.cfg_scale,
            "validation_status": "mock",
        }
        weights = {"mot": {"id": "mock", "files": {}}, "vae": {"id": "mock", "files": {}}}
        identity = hashlib.sha256(
            json.dumps({"request": effective, "weights": weights}, sort_keys=True).encode()
        ).hexdigest()
        return BackendResult(
            plan=plan,
            tokens=tokens,
            audio=audio,
            effective_config=effective,
            weights=weights,
            runtime={"backend": "mock", "latent_frame_rate": LATENT_FRAME_RATE},
            request_identity=identity,
            semantic_tokens=None,
            budget={
                **self._budget,
                "semantic": {
                    "budget_tokens": config.sampling.max_tokens,
                    "tokens_generated": tokens.semantic_token_count,
                    "termination_reason": self._termination,
                },
            },
            termination_reason=self._termination,
            adjustments=list(self._adjustments),
        )

    async def cancel(self, job_id: str) -> None:
        return None

    async def shutdown(self) -> None:
        return None
