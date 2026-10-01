"""Model lifecycle.

The 7.26 GB checkpoint is loaded once and kept resident between jobs. It is
only rebuilt when a job asks for a different model, decoder, precision or
memory budget, and it is only torn down when the idle policy says so.
"""
from __future__ import annotations

import logging
import gc
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yue2_studio_core.errors import ConflictError, ErrorCode, StudioError, classify_exception
from yue2_studio_core.model_metadata import describe_model_files, resolve_model_reference, resolve_vae_reference, vae_compatibility_error
from yue2_studio_core.model_files import model_file_leases
from yue2_studio_core.model_lifecycle import ModelLifecycle
from yue2_studio_core.model_registry import ModelRegistry
from yue2_studio_core.hardware import precision_capabilities, system_memory
from yue2_studio_core.model_recommendations import assess_model, gpu_capacity
from yue2_studio_core.models import GenerationConfig
from yue2_studio_core.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineKey:
    """Everything that forces a reload if it changes."""

    device_index: int
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
    def __init__(self, settings: Settings, store=None) -> None:
        self.settings = settings
        self._store = store
        self._lock = threading.RLock()
        self._pipeline: Any = None
        self._key: PipelineKey | None = None
        self._loaded_at: float | None = None
        self._last_used: float | None = None
        self._files_lease = None
        self._cleanup_device: int | None = None
        self._snapshot: dict = {}
        self._publish(ModelLifecycle.UNLOADED)

    # -- device ------------------------------------------------------------ #

    @property
    def device_index(self) -> int:
        """The GPU chosen on the System page, defaulting to the first visible one.

        Read fresh rather than cached: the user can change it while the worker
        is idle, and the next job should honour it without a restart.
        """
        if self._store is None:
            return 0
        return self._store.device_index()

    @property
    def device(self) -> str:
        return f"cuda:{self.device_index}"

    # -- resolution -------------------------------------------------------- #

    def resolve_model(self, config: GenerationConfig) -> str:
        """The model directory to load.

        ``DEFAULT_MODEL`` is a sentinel meaning "whatever .env configures", not
        a path; it must be resolved here rather than handed to the runtime.
        """
        return resolve_model_reference(config.model.checkpoint, self.settings)

    def resolve_vae(self, config: GenerationConfig) -> str:
        return resolve_vae_reference(config.model.vae, self.settings)

    def key_for(self, config: GenerationConfig, device_index: int | None = None) -> PipelineKey:
        return PipelineKey(
            device_index=self.device_index if device_index is None else device_index,
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
        model = self.resolve_model(config)
        entry = (ModelRegistry(self.settings, self._store).describe(model) if self._store else describe_model_files(model, "model"))
        references = [("model", model)]
        if entry.format != "gguf":
            references.append(("vae", self.resolve_vae(config)))
        for role, reference in references:
            path = Path(reference)
            if path.is_absolute() or reference.startswith(".") or path.is_dir():
                entry = (ModelRegistry(self.settings, self._store).describe(reference, role) if self._store else describe_model_files(reference, role))
                if not entry.inference_ready:
                    code = (ErrorCode.MODEL_NOT_FOUND if entry.inference_status == "files_missing" else
                            ErrorCode.INVALID_CONFIG if entry.inference_status == "validation_failed" else ErrorCode.UNSUPPORTED_CAPABILITY)
                    raise StudioError(code, f"The {role} at {reference} is unavailable: {entry.problem}", stage="loading_model")
            elif config.model.local_files_only:
                raise StudioError(
                    ErrorCode.MODEL_NOT_FOUND,
                    f"The {role} '{reference}' is not a local directory and offline mode is on.",
                    stage="loading_model",
                )
        if len(references) == 2 and all(Path(ref).is_dir() for _, ref in references):
            if problem := vae_compatibility_error(model, self.resolve_vae(config)):
                raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, problem, stage="loading_model")

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

    def acquire(self, config: GenerationConfig, device_index: int | None = None) -> tuple[Any, bool]:
        """Return a pipeline for this configuration and whether it was loaded now."""
        with self._lock:
            if self._snapshot["lifecycle"] in {ModelLifecycle.IN_USE.value, ModelLifecycle.UNLOAD_FAILED.value}:
                raise ConflictError("Finish active inference or successfully unload failed resources before loading a model.")
            key = self.key_for(config, device_index)
            if describe_model_files(key.model, "model").format == "gguf":
                raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, "GGUF requires the per-job audio.cpp adapter; this manager owns native pipelines.", stage="loading_model")
            # Recheck even when reusing weights: stale/failed validation must
            # not be bypassed by an already-resident pipeline.
            try:
                self.verify_files(config)
            except StudioError as exc:
                self._publish(ModelLifecycle(self._snapshot["lifecycle"]) if self._pipeline else ModelLifecycle.LOAD_FAILED, error=exc.to_dict())
                raise
            if self._pipeline is not None and self._key == key:
                self._last_used = time.time()
                self._publish(ModelLifecycle.IDLE)
                return self._pipeline, False

            if self._pipeline is not None:
                logger.info("releasing the resident pipeline: configuration changed")
                self.release()

            lease = model_file_leases(self._store, [key.model, key.vae]) if self._store else None
            if lease is not None:
                lease.__enter__()
                self._files_lease = lease
            self._key = key
            self._publish(ModelLifecycle.LOADING, key=key)
            try:
                self._check_runtime(config, key)
                self._cleanup_device = key.device_index
                result = self._load(config, key)
                self._publish(ModelLifecycle.LOADED)
                return result
            except BaseException as exc:
                try:
                    self.release()
                except Exception:
                    raise  # conservative cleanup failure blocks another load
                error = exc.to_dict() if isinstance(exc, StudioError) else dict(error_code=classify_exception(exc).value, error_message=str(exc))
                self._publish(ModelLifecycle.LOAD_FAILED, error=error)
                raise

    def _check_runtime(self, config: GenerationConfig, key: PipelineKey) -> None:
        """Fresh worker-side device and shared safety estimate before allocation."""
        try:
            import torch
        except ImportError as exc:
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, "PyTorch is unavailable in the GPU worker environment; check the worker installation.", stage="loading_model") from exc

        if not torch.cuda.is_available() or key.device_index not in range(torch.cuda.device_count()):
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, f"GPU {key.device_index} is unavailable in this worker.", stage="loading_model")
        properties = torch.cuda.get_device_properties(key.device_index)
        precision = precision_capabilities((properties.major, properties.minor))
        if precision["bf16_supported"] is False or (key.quantization == "fp8" and precision["fp8_supported"] is False):
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, "The selected GPU lacks the requested native precision capability.", stage="loading_model")
        free, total = torch.cuda.mem_get_info(key.device_index)
        device = dict(index=key.device_index, selectable=True, cuda_available=True,
                      memory_total_bytes=total, memory_free_bytes=free, **precision)
        describe = ModelRegistry(self.settings, self._store).describe if self._store else describe_model_files
        assessment = assess_model(describe(key.model, "model"), device=device, capacity=gpu_capacity(device, self.settings),
                                  vae=describe(key.vae, "vae"), settings=self.settings,
                                  runtime={"backend": "native", "native_available": True}, ram=system_memory(),
                                  offload_ar=key.offload_ar, compute_backend=key.backend, memory_budget_gib=key.memory_budget_gib)
        if assessment["excess_bytes"]:
            excess = assessment["excess_bytes"] / 2**30
            raise StudioError(ErrorCode.CUDA_OOM, f"Estimated runtime VRAM for {key.model} on GPU {key.device_index} exceeds the configured safe budget by {excess:.2f} GiB. Free VRAM or choose a smaller model/configuration; this is an estimate.",
                              stage="loading_model", details={"assessment": assessment})

    def _load(self, config: GenerationConfig, key: PipelineKey) -> tuple[Any, bool]:
        try:
            from yue2 import YuE2Pipeline
            from yue2.protocol import GenerationConfig as NativeGenerationConfig
        except ImportError as exc:
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, "The native YuE2 runtime is unavailable in this worker environment; check the worker installation.", stage="loading_model") from exc

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
                device=f"cuda:{key.device_index}",
                memory_budget_gib=key.memory_budget_gib,
                backend=key.backend,
                quantization=key.quantization,
                offload_ar=key.offload_ar,
                vae_core_frames=key.vae_core_frames,
                generation_config=native_config,
                progress=False,
            )
            if key.backend != "vllm":
                # Pinned yue2-infer from_pretrained resolves files but leaves
                # tensors lazy. Materialize the native model before LOADED.
                self._pipeline._load_model()
        except FileNotFoundError as exc:
            raise StudioError(ErrorCode.MODEL_NOT_FOUND, str(exc), stage="loading_model") from exc
        except Exception as exc:
            code = ErrorCode.CUDA_OOM if classify_exception(exc) is ErrorCode.CUDA_OOM else ErrorCode.MODEL_LOAD_FAILED
            raise StudioError(code, str(exc), stage="loading_model") from exc
        self._key = key
        self._loaded_at = time.time()
        self._last_used = self._loaded_at
        logger.info("pipeline ready in %.1fs", time.perf_counter() - started)
        return self._pipeline, True

    def release(self) -> None:
        with self._lock:
            if self._snapshot["lifecycle"] == ModelLifecycle.IN_USE.value:
                raise ConflictError("The model is in use. Unload runs after the active inference operation finishes.")
            pipeline = self._pipeline
            self._publish(ModelLifecycle.UNLOADING)
            try:
                if pipeline is not None:
                    pipeline.close()
                    self._pipeline = None
                    del pipeline
                    gc.collect()
                if self._cleanup_device is not None:
                    self._clear_cuda(self._cleanup_device)
                if self._files_lease is not None:
                    self._files_lease.__exit__(None, None, None)
                    self._files_lease = None
            except Exception as exc:
                error = StudioError(ErrorCode.MODEL_UNLOAD_FAILED, f"Model resource cleanup failed: {exc}", stage="unloading_model")
                self._publish(ModelLifecycle.UNLOAD_FAILED, error=error.to_dict())
                raise error from exc
            self._key = None
            self._cleanup_device = None
            self._loaded_at = None
            self._last_used = None
            self._publish(ModelLifecycle.UNLOADED)

    @staticmethod
    def _clear_cuda(device_index: int) -> None:
        import torch

        with torch.cuda.device(device_index):
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

    def begin_use(self) -> None:
        with self._lock:
            if self._pipeline is None or self._snapshot["lifecycle"] not in {ModelLifecycle.LOADED.value, ModelLifecycle.IDLE.value}:
                raise ConflictError("A resident pipeline is required before starting inference.")
            self._publish(ModelLifecycle.IN_USE)

    def end_use(self) -> None:
        with self._lock:
            if self._snapshot["lifecycle"] == ModelLifecycle.IN_USE.value and self._pipeline is not None:
                self._last_used = time.time()
                self._publish(ModelLifecycle.IDLE)

    def external_started(self, config: GenerationConfig, device_index: int, pid: int) -> None:
        with self._lock:
            if self._pipeline is not None or self._snapshot["lifecycle"] != ModelLifecycle.UNLOADED.value:
                raise ConflictError("Release native resources before starting an audio.cpp process.")
            # The CLI has no residency probe. Process activity is observable;
            # loaded tensor/GPU memory is explicitly unknown, not assumed.
            self._snapshot = {**self._snapshot, "lifecycle": ModelLifecycle.IN_USE.value,
                              "model": self.resolve_model(config), "vae": str(Path(self.resolve_model(config)) / "yue2-vae-f16.gguf"),
                              "device_index": device_index, "backend": "audiocpp", "residency_mode": "per_job",
                              "residency_known": False, "process_id": pid, "model_gpu_resident": None, "vae_gpu_resident": None}

    def external_finished(self) -> None:
        with self._lock:
            if self._snapshot.get("residency_mode") == "per_job":
                self._publish(ModelLifecycle.UNLOADED)

    def release_if_device_changed(self) -> bool:
        with self._lock:
            if self._snapshot["lifecycle"] == ModelLifecycle.UNLOAD_FAILED.value:
                return False  # explicit unload retry must resolve uncertain cleanup
            if self._key is None or self._key.device_index == self.device_index:
                return False
            self.release()
            return True

    def maybe_unload_idle(self) -> bool:
        """Honour MODEL_IDLE_UNLOAD_SECONDS. 0 keeps the model resident."""
        timeout = self.settings.model_idle_unload_seconds
        if timeout <= 0:
            return False
        with self._lock:
            if self._snapshot["lifecycle"] in {ModelLifecycle.IN_USE.value, ModelLifecycle.UNLOAD_FAILED.value}:
                return False
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

    @staticmethod
    def _placement(module) -> tuple[str | None, bool | None]:
        if module is None:
            return None, False
        try:
            device = next(module.parameters()).device
            return str(device), device.type == "cuda"
        except (AttributeError, StopIteration):
            return None, None

    def _residency(self, pipeline) -> dict:
        model = getattr(pipeline, "_model", None)
        vae = getattr(pipeline, "_vae", None)
        child = getattr(pipeline, "_vllm_worker", None)
        tensors_known = pipeline is None or hasattr(pipeline, "_model")
        model_device, model_gpu = self._placement(model)
        vae_device, vae_gpu = self._placement(vae)
        return dict(pipeline_ready=pipeline is not None,
                    loaded=pipeline is not None and (not tensors_known or model is not None or vae is not None or child is not None),
                    model_device=model_device, vae_device=vae_device,
                    model_gpu_resident=model_gpu if tensors_known and child is None else None,
                    vae_gpu_resident=vae_gpu if tensors_known else None,
                    residency_known=tensors_known and child is None)

    def _publish(self, lifecycle: ModelLifecycle, *, key: PipelineKey | None = None, error: dict | None = None) -> None:
        key = key or self._key
        snapshot = {
                "lifecycle": lifecycle.value, "error": error,
                **self._residency(self._pipeline),
                "model": key.model if key else None,
                "vae": key.vae if key else None,
                "backend": key.backend if key else None,
                "quantization": key.quantization if key else None,
                "device_index": key.device_index if key else None,
                "loaded_at": self._loaded_at,
                "last_used": self._last_used,
                "weights": getattr(self._pipeline, "weights", None) if self._pipeline else None,
                "runtime_sha256": getattr(self._pipeline, "runtime_sha256", None) if self._pipeline else None,
                "residency_mode": "persistent", "process_id": None,
            }
        if lifecycle is ModelLifecycle.UNLOAD_FAILED:
            snapshot["residency_known"] = False
        self._snapshot = snapshot

    def state(self) -> dict:
        # Operation lock intentionally excluded: heartbeat must observe LOADING
        # and UNLOADING while the blocking runtime call holds that lock.
        snapshot = dict(self._snapshot)
        if snapshot["lifecycle"] == ModelLifecycle.IN_USE.value and snapshot["residency_mode"] == "persistent":
            # Native decode/offload may move weights to CPU during a job.
            # Tensor device metadata is readable without allocating CUDA data.
            snapshot.update(self._residency(self._pipeline))
        used = snapshot.pop("last_used")
        snapshot["idle_seconds"] = time.time() - used if used and snapshot["lifecycle"] != ModelLifecycle.IN_USE.value else None
        return snapshot

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
        versions["runtime_sha256"] = self._snapshot.get("runtime_sha256")
        return versions
