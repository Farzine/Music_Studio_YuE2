"""YuE2 GGUF inference through the audio.cpp CLI (one process per job)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf
from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.manifest import identity
from yue2_studio_core.models import GenerationConfig, GenerationMode, JobStatus
from yue2_studio_core.parameters import gguf_unsupported_parameters
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store, sha256_file

from .base import AudioTokensResult, BackendResult, DecodedAudio, GenerationContext, PlanResult


class AudioCppBackend:
    name = "audiocpp"

    def __init__(self, settings: Settings, store: Store, device_index: int | None = None) -> None:
        self.settings = settings
        self.store = store
        self.device_index = store.device_index() if device_index is None else device_index
        self._audio: np.ndarray | None = None
        self._rate = 48000
        self._semantic: np.ndarray | None = None
        self._truncated = False

    async def get_capabilities(self) -> dict:
        return {"backend": self.name, "modes": ["full", "melody", "off", "score_edit"]}

    async def validate_config(self, config: GenerationConfig) -> list[str]:
        unsupported = gguf_unsupported_parameters(config)
        if config.prompt.mode is GenerationMode.COVER:
            unsupported.append("cover mode")
        if unsupported:
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, "GGUF does not support: " + ", ".join(unsupported), stage="validation")
        if not shutil.which(self.settings.audiocpp_executable) and not (
            Path(self.settings.audiocpp_executable).is_file() and os.access(self.settings.audiocpp_executable, os.X_OK)
        ):
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, "audio.cpp CLI is not installed. Set AUDIOCPP_CLI_PATH to audiocpp_cli.", stage="validation")
        metadata = Path(config.model.checkpoint) / "studio-model.json"
        if not metadata.is_file():
            raise StudioError(ErrorCode.MODEL_NOT_FOUND, "GGUF model metadata is missing.", stage="validation")
        return (["audio.cpp uses its own duration handling; automatic fit-to-plan is unavailable."]
                if config.sampling.fit_to_plan else [])

    async def prepare(self, config: GenerationConfig, context: GenerationContext) -> None:
        self._audio = None
        self._semantic = None
        self._truncated = False
        context.reporter.begin(JobStatus.LOADING_MODEL, "loading_model", "Preparing GGUF model")

    async def generate_plan(self, context: GenerationContext) -> PlanResult:
        config = context.config
        root = Path(config.model.checkpoint)
        metadata = json.loads((root / "studio-model.json").read_text(encoding="utf-8"))
        filename = metadata["filename"]
        job = self.store.get_job(context.job_id)
        output = self.store.generation_dir(job.project_id, job.id) / "audiocpp"
        output.mkdir(parents=True, exist_ok=True)
        wav = output / "song.wav"
        options = {
            "style": config.prompt.style,
            "cot": config.prompt.mode.cot,
            "num_inference_steps": config.synthesis.ode_steps,
            "abc_max_tokens": config.planner.max_tokens,
            "semantic_max_tokens": config.sampling.max_tokens,
            "export_semantic": "true",
        }
        for prefix, block in (("abc", config.planner), ("semantic", config.sampling)):
            for name in ("temperature", "top_p", "top_k", "repetition_penalty", "penalty_window", "min_tokens"):
                options[f"{prefix}_{name}"] = getattr(block, name)
        if config.synthesis.cfg_scale is not None:
            options["guidance_scale"] = config.synthesis.cfg_scale
        if config.prompt.abc.strip():
            options["abc"] = config.prompt.abc
        command = [
            self.settings.audiocpp_executable, "--task", "gen", "--family", "yue2",
            "--model", str(root), "--backend", "cuda", "--device", str(self.device_index),
            "--lyrics", config.prompt.lyrics, "--seed", str(config.sampling.seed),
            "--session-option", f"yue2.model_gguf={filename}",
            "--session-option", "yue2.vae_gguf=yue2-vae-f16.gguf",
            "--out", str(wav), "--out-dir", str(output),
        ]
        for name, value in options.items():
            command += ["--request-option", f"{name}={value}"]
        context.reporter.begin(JobStatus.GENERATING, "generating", "Generating song with audio.cpp")
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        communication = asyncio.create_task(process.communicate())
        try:
            while not communication.done():
                if context.cancelled():
                    if process.returncode is None:
                        try:
                            process.terminate()
                        except ProcessLookupError:
                            pass
                    try:
                        await asyncio.wait_for(asyncio.shield(communication), timeout=10)
                    except asyncio.TimeoutError:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        await communication
                    raise StudioError(ErrorCode.CANCELLED, "GGUF generation cancelled.", stage="generating")
                await asyncio.sleep(0.25)
            stdout, _ = await communication
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        if process.returncode or not wav.is_file():
            raise StudioError(
                ErrorCode.INFERENCE_FAILED,
                f"audio.cpp generation failed: {stdout.decode(errors='replace')[-800:]}",
                stage="generating",
            )
        self._audio, self._rate = sf.read(wav, dtype="float32", always_2d=True)
        semantic = output / "semantic.json"
        if semantic.is_file():
            self._semantic = np.asarray(json.loads(semantic.read_text(encoding="utf-8")), dtype=np.int32)
            self._truncated = self._semantic.size >= config.sampling.max_tokens
        score = output / "score.abc"
        abc = score.read_text(encoding="utf-8") if score.is_file() else config.prompt.abc or None
        return PlanResult(abc=abc, abc_token_count=0, truncated=False)

    async def generate_audio(self, context: GenerationContext, plan: PlanResult) -> AudioTokensResult:
        return AudioTokensResult(
            latents=np.empty(0, dtype=np.float32),
            semantic_token_count=int(self._semantic.size) if self._semantic is not None else 0,
            truncated=self._truncated,
        )

    async def decode_audio(self, context: GenerationContext, tokens: AudioTokensResult) -> DecodedAudio:
        if self._audio is None:
            raise StudioError(ErrorCode.INFERENCE_FAILED, "audio.cpp produced no audio.", stage="decoding")
        return DecodedAudio(audio=self._audio, sample_rate=self._rate)

    async def finalise(self, context: GenerationContext, plan: PlanResult, tokens: AudioTokensResult, audio: DecodedAudio) -> BackendResult:
        config = context.config
        root = Path(config.model.checkpoint)
        metadata = json.loads((root / "studio-model.json").read_text(encoding="utf-8"))
        weights = {
            "model": {"file": metadata["filename"], "sha256": sha256_file(root / metadata["filename"])},
            "vae": {"file": "yue2-vae-f16.gguf", "sha256": sha256_file(root / "yue2-vae-f16.gguf")},
        }
        executable = shutil.which(self.settings.audiocpp_executable) or self.settings.audiocpp_executable
        effective = config.model_dump(mode="json")
        effective["runtime_backend"] = self.name
        adjustments = []
        if config.sampling.fit_to_plan:
            effective["sampling"]["fit_to_plan"] = False
            adjustments.append({"parameter": "sampling.fit_to_plan", "requested": True, "effective": False,
                                "reason": "audio.cpp does not expose this policy"})
        return BackendResult(
            plan=plan, tokens=tokens, audio=audio, effective_config=effective, weights=weights,
            runtime={"backend": self.name, "model_revision": metadata.get("revision"),
                     "cli_sha256": sha256_file(Path(executable))},
            request_identity=identity({"request": effective, "weights": weights}),
            semantic_tokens=self._semantic,
            termination_reason="MAX_TOKENS" if self._truncated else "EOS",
            adjustments=adjustments,
        )

    async def cancel(self, job_id: str) -> None:
        pass

    async def shutdown(self) -> None:
        self._audio = None
        self._semantic = None
