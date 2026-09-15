"""Model lifecycle.

The 7.26 GB checkpoint is loaded once and kept resident between jobs. It is
only rebuilt when a job asks for a different model, decoder, precision or
memory budget, and it is only torn down when the idle policy says so.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.models import GenerationConfig
from yue2_studio_core.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineKey:
    """Everything that forces a reload if it changes."""

    model: str
    revision: str | None
    vae: str
    vae_revision: str | None
    backend: str
    quantization: str
    offload_ar: bool
    memory_budget_gib: float
    local_files_only: bool
    vae_core_frames: int
    ode_steps: int


class ModelManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._pipeline: Any = None
        self._key: PipelineKey | None = None
        self._loaded_at: float | None = None
        self._last_used: float | None = None

    # -- resolution -------------------------------------------------------- #

    def resolve_model(self, config: GenerationConfig) -> str:
        return config.model.checkpoint.strip() or self.settings.model_reference

    def resolve_vae(self, config: GenerationConfig) -> str:
        choice = config.model.vae
        if choice == "standard":
            return self.settings.vae_reference
        if choice == "legacy":
            return self.settings.vae_legacy_reference
        return choice

    def key_for(self, config: GenerationConfig) -> PipelineKey:
        return PipelineKey(
            model=self.resolve_model(config),
            revision=config.model.revision,
            vae=self.resolve_vae(config),
            vae_revision=config.model.vae_revision,
            backend=config.model.compute_backend,
            quantization=config.model.quantization,
            offload_ar=config.model.offload_ar,
            memory_budget_gib=config.model.memory_budget_gib,
            local_files_only=config.model.local_files_only,
            vae_core_frames=config.decoder.tile_frames,
            ode_steps=config.synthesis.ode_steps,
        )

    # -- lifecycle --------------------------------------------------------- #

    def verify_files(self, config: GenerationConfig) -> None:
        """Fail early with a precise reason instead of deep inside the runtime."""
        for role, reference in (("model", self.resolve_model(config)), ("decoder", self.resolve_vae(config))):
            path = Path(reference)
            if path.is_absolute() or reference.startswith("."):
                if not path.is_dir():
                    raise StudioError(
                        ErrorCode.MODEL_NOT_FOUND,
                        f"The {role} directory {reference} does not exist.",
                        stage="loading_model",
                    )
                if not (path / "config.json").is_file():
                    raise StudioError(
                        ErrorCode.MODEL_NOT_FOUND,
                        f"The {role} directory {reference} has no config.json.",
                        stage="loading_model",
                    )
                if not (path / "model.safetensors").is_file():
                    raise StudioError(
                        ErrorCode.MODEL_NOT_FOUND,
                        f"The {role} directory {reference} has no model.safetensors.",
                        stage="loading_model",
                    )
            elif config.model.local_files_only:
                raise StudioError(
                    ErrorCode.MODEL_NOT_FOUND,
                    f"The {role} '{reference}' is not a local directory and offline mode is on.",
                    stage="loading_model",
                )

    @staticmethod
    def native_sampling(config: GenerationConfig) -> tuple[Any, Any]:
        """Per-request sampling for the planner and the acoustic stage.

        These are passed to ``plan()`` and ``generate_semantic()`` on every call
        rather than baked into the pipeline, so changing a sampling value never
        forces a 7.26 GB reload — and, more importantly, a resident pipeline can
        never apply a previous job's token budget to this one.
        """
        from yue2.protocol import Sampling

        planner = Sampling(
            temperature=config.planner.temperature,
            top_p=config.planner.top_p,
            top_k=config.planner.top_k,
            repetition_penalty=config.planner.repetition_penalty,
            penalty_window=config.planner.penalty_window,
            min_tokens=config.planner.min_tokens,
            max_tokens=config.planner.max_tokens,
        )
        semantic = Sampling(
            temperature=config.sampling.temperature,
            top_p=config.sampling.top_p,
            top_k=config.sampling.top_k,
            repetition_penalty=config.sampling.repetition_penalty,
            penalty_window=config.sampling.penalty_window,
            min_tokens=config.sampling.min_tokens,
            max_tokens=config.sampling.max_tokens,
        )
        return planner, semantic

    def acquire(self, config: GenerationConfig) -> tuple[Any, bool]:
        """Return a pipeline for this configuration and whether it was loaded now."""
        from yue2 import YuE2Pipeline  # imported lazily: the API never needs it
        from yue2.protocol import GenerationConfig as NativeGenerationConfig

        with self._lock:
            key = self.key_for(config)
            if self._pipeline is not None and self._key == key:
                self._last_used = time.time()
                return self._pipeline, False

            if self._pipeline is not None:
                logger.info("releasing the resident pipeline: configuration changed")
                self.release()

            self.verify_files(config)
            planner_sampling, semantic_sampling = self.native_sampling(config)
            # ode_steps is a pipeline-level setting (synthesize() reads it from
            # the pipeline), so it is part of PipelineKey. Sampling is not: it is
            # supplied per call.
            native_config = NativeGenerationConfig(
                abc=planner_sampling,
                semantic=semantic_sampling,
                ode_steps=config.synthesis.ode_steps,
            )
            started = time.perf_counter()
            try:
                self._pipeline = YuE2Pipeline.from_pretrained(
                    key.model,
                    vae=key.vae,
                    revision=key.revision,
                    vae_revision=key.vae_revision,
                    local_files_only=key.local_files_only,
                    device="cuda",
                    memory_budget_gib=key.memory_budget_gib,
                    backend=key.backend,
                    quantization=key.quantization,
                    offload_ar=key.offload_ar,
                    vae_core_frames=key.vae_core_frames,
                    generation_config=native_config,
                    progress=False,
                )
            except FileNotFoundError as exc:
                raise StudioError(ErrorCode.MODEL_NOT_FOUND, str(exc), stage="loading_model") from exc
            except Exception as exc:
                raise StudioError(ErrorCode.MODEL_LOAD_FAILED, str(exc), stage="loading_model") from exc
            self._key = key
            self._loaded_at = time.time()
            self._last_used = self._loaded_at
            logger.info("pipeline ready in %.1fs", time.perf_counter() - started)
            return self._pipeline, True

    def release(self) -> None:
        with self._lock:
            if self._pipeline is not None:
                try:
                    self._pipeline.close()
                except Exception:
                    logger.exception("closing the pipeline failed")
            self._pipeline = None
            self._key = None
            self._loaded_at = None

    def maybe_unload_idle(self) -> bool:
        """Honour MODEL_IDLE_UNLOAD_SECONDS. 0 keeps the model resident."""
        timeout = self.settings.model_idle_unload_seconds
        if timeout <= 0:
            return False
        with self._lock:
            if self._pipeline is None or self._last_used is None:
                return False
            if time.time() - self._last_used < timeout:
                return False
            logger.info("unloading the model after %ss idle", timeout)
            self.release()
            return True

    # -- introspection ----------------------------------------------------- #

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    def state(self) -> dict:
        with self._lock:
            return {
                "loaded": self._pipeline is not None,
                "model": self._key.model if self._key else None,
                "vae": self._key.vae if self._key else None,
                "backend": self._key.backend if self._key else None,
                "quantization": self._key.quantization if self._key else None,
                "loaded_at": self._loaded_at,
                "idle_seconds": (time.time() - self._last_used) if self._last_used else None,
                "weights": getattr(self._pipeline, "weights", None) if self._pipeline else None,
            }

    def runtime_versions(self) -> dict:
        import importlib.metadata

        versions: dict[str, str | None] = {}
        for package in ("torch", "transformers", "safetensors", "tiktoken", "soundfile", "accelerate", "yue2-infer"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
        try:
            import torch

            versions["cuda"] = torch.version.cuda
            versions["cudnn"] = str(torch.backends.cudnn.version())
        except Exception:
            versions["cuda"] = None
        with self._lock:
            versions["runtime_sha256"] = getattr(self._pipeline, "runtime_sha256", None) if self._pipeline else None
        return versions
