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
        context.reporter.begin(JobStatus.LOADING_MODEL, "loading_model", "Loading model")
        await asyncio.sleep(0.2)

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
        frames = min(config.sampling.max_tokens, int(20 * LATENT_FRAME_RATE))
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
            truncated=False,
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
        )

    async def cancel(self, job_id: str) -> None:
        return None

    async def shutdown(self) -> None:
        return None
