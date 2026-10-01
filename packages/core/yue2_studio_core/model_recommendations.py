"""Explainable memory estimates over shared model facts, without inference imports.

These are planning estimates, never a successful load test. The current adapters
supply compatibility; unsupported families do not acquire a runtime here.
"""
from __future__ import annotations

import math
from pathlib import Path

from .budget import kv_cache_bytes_per_token
from .model_metadata import ModelMetadata, read_json_object, vae_config_compatibility_error
from .settings import Settings

GIB = 2**30
STATUS_ORDER = {name: index for index, name in enumerate((
    "ready", "recommended", "supported", "possibly_supported", "not_recommended", "unknown", "cannot_run",
))}
# Effective storage bits include a little block/scales overhead. They describe
# hypothetical capacity, never an inferred parameter count for a real model.
CAPACITY_BITS = {"Q4": 4.5, "Q5": 5.5, "Q8": 8.5, "BF16": 16.0}


def _number(value) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def gpu_capacity(device: dict, settings: Settings) -> dict:
    total, free = _number(device.get("memory_total_bytes")), _number(device.get("memory_free_bytes"))
    known = bool(device.get("selectable") and device.get("cuda_available") is True
                 and total and free is not None and free <= total)
    reserve = math.ceil(max((total or 0) * settings.model_vram_safety_fraction,
                            settings.model_vram_safety_gib * GIB))
    # Only idle, manager-owned PyTorch allocations may be recovered. CUDA
    # contexts/other processes/audio.cpp memory are not assumed reclaimable.
    reclaimable = 0
    if known and device.get("loaded_model") and not device.get("worker_busy"):
        reclaimable = min(_number(device.get("reserved_bytes")) or 0, total - free)
    available = free + reclaimable if known else None
    usable = max(0, available - reserve) if known else None
    fixed = math.ceil((settings.model_runtime_overhead_gib + settings.model_unknown_kv_gib
                       + settings.model_unknown_vae_gib) * GIB)
    upper = max(0, int((usable - fixed) / settings.model_weight_overhead_factor)) if known else None
    comfortable = max(0, int((usable - fixed) / (settings.model_weight_overhead_factor * 1.2))) if known else None
    conservative = int(comfortable * 0.8) if comfortable is not None else None
    precision = []
    for quant, bits in CAPACITY_BITS.items():
        eligible = device.get("bf16_supported") if quant == "BF16" else None
        precision.append(dict(quantization=quant, effective_storage_bits=bits,
                              approximate_parameters=math.floor(comfortable * 8 / bits) if known else None,
                              hardware_eligible=eligible))
    reasons = ["Heuristic capacity reserves VAE, cache and runtime workspace; actual model metadata overrides these defaults."]
    if not known:
        reasons.append("Worker CUDA device or current free VRAM is unconfirmed.")
    if reclaimable:
        reasons.append("Capacity assumes the idle loaded model is unloaded and its allocator cache released first.")
    if device.get("worker_busy"):
        reasons.append("Inference is active; no resident memory is counted as reclaimable.")
    return dict(device_index=device["index"], name=device.get("name"), basis="heuristic",
                free_bytes=free, available_bytes=available, reclaimable_bytes=reclaimable,
                usable_bytes=usable, safety_margin_bytes=reserve if known else None,
                fixed_overhead_bytes=fixed, comfortable_model_bytes=comfortable,
                conservative_model_bytes=conservative, upper_model_bytes=upper,
                quantizations=precision, reasons=reasons)


def _config(model: ModelMetadata) -> dict:
    if not model.path:
        return {}
    filename = "sidecars/yue2-model-config.json" if model.format == "gguf" else "config.json"
    try:
        return read_json_object(Path(model.path) / filename)
    except (OSError, ValueError):
        return {}


def _vae_weights(model: ModelMetadata, vae: ModelMetadata | None, settings: Settings) -> tuple[int, bool]:
    if model.format == "gguf" and model.path:
        try:
            return (Path(model.path) / "yue2-vae-f16.gguf").stat().st_size, True
        except OSError:
            pass
    elif vae and (_number(vae.bytes) or 0) > 0 and vae.inference_ready:
        # The native decoder is FP32 even when its stored weights are FP16.
        factor = 1 if (vae.precision or "").upper() in {"F32", "FP32", "FLOAT32"} else 2
        return max(vae.bytes * factor, (_number(vae.parameter_count) or 0) * 4), True
    return math.ceil(settings.model_unknown_vae_gib * GIB), False


def model_memory(model: ModelMetadata, vae: ModelMetadata | None, settings: Settings, *,
                 model_config: dict | None = None, bundled_vae_bytes: int | None = None) -> dict:
    """Conservative sum of phases; offload never discounts full-load weights.

    ponytail: assumes full declared context and two CFG branches, tiled decode;
    request-specific peaks/observed profiles can refine this once collected.
    """
    weights = _number(model.bytes) or None
    if model.backend == "native" and weights is not None:
        weights = max(weights, (_number(model.parameter_count) or 0) * 2)  # BF16 loader
    config = _config(model) if model_config is None else model_config
    valid_dimensions = all(type(config.get(key)) is int and 0 < config[key] <= 2**31 - 1
                           for key in ("num_hidden_layers", "num_key_value_heads", "head_dim"))
    per_token = kv_cache_bytes_per_token(config) if valid_dimensions else 0
    context = config.get("max_position_embeddings")
    exact_kv = bool(per_token and type(context) is int and 0 < context <= 2**31 - 1)
    kv = per_token * context * 2 if exact_kv else math.ceil(settings.model_unknown_kv_gib * GIB)
    vae_bytes, known_vae = _vae_weights(model, vae, settings)
    if model.format == "gguf" and (_number(bundled_vae_bytes) or 0) > 0:
        vae_bytes, known_vae = bundled_vae_bytes, True
    workspace = math.ceil(settings.model_runtime_overhead_gib * GIB)
    expanded = math.ceil(weights * settings.model_weight_overhead_factor) if weights is not None else None
    peak = expanded + vae_bytes + kv + workspace if expanded is not None else None
    return dict(basis="metadata_and_heuristics" if exact_kv or known_vae else "heuristic",
                weights_bytes=weights, weight_runtime_bytes=expanded, vae_bytes=vae_bytes,
                vae_size_known=known_vae, kv_cache_bytes=kv,
                kv_source="model_config_full_context_two_cfg_branches" if exact_kv else "configured_fallback",
                runtime_overhead_bytes=workspace, estimated_peak_bytes=peak,
                conservative_peak_bytes=math.ceil(expanded * 1.2) + vae_bytes + kv + workspace if expanded is not None else None,
                estimated_system_ram_bytes=math.ceil((weights + vae_bytes) * 1.5) if weights is not None else None,
                assumptions=["Full declared context and two CFG branches when available; otherwise a configured cache reserve.",
                             "Tiled VAE decode; runtime workspace and weight expansion are heuristic.",
                             "Model and VAE costs are summed conservatively across phases; no offload load-time discount."])


def assess_model(model: ModelMetadata, *, device: dict, capacity: dict, vae: ModelMetadata | None,
                 settings: Settings, runtime: dict, ram: dict, offload_ar: bool = False,
                 compute_backend: str = "torch", memory_budget_gib: float = 40,
                 model_config: dict | None = None, bundled_vae_bytes: int | None = None) -> dict:
    estimate = model_memory(model, vae, settings, model_config=model_config, bundled_vae_bytes=bundled_vae_bytes)
    reasons, blockers, unknowns = [], [], []
    loaded = device.get("loaded_model") in [model.id, *model.aliases]
    backend = model.backend
    if model.format not in {"gguf", "safetensors"} or backend not in {"native", "audiocpp"}:
        blockers.append("No installed inference adapter supports this model format/backend.")
    if model.compatibility_status == "incompatible" or model.inference_status in {"incompatible", "validation_failed"} or model.validation_status == "failed":
        blockers.append(model.problem or "The model failed format, architecture or structural checks.")
    elif model.compatibility_status == "unknown":
        unknowns.append(model.problem or "Model architecture/runtime compatibility needs validation.")
    if not model.architecture:
        unknowns.append("Model architecture is unknown; a file-size fit cannot confirm runtime compatibility.")
    if model.parameter_count is not None and not _number(model.parameter_count):
        unknowns.append("Declared parameter count is outside the supported metadata range.")
    config = _config(model) if model_config is None else model_config
    if any(type(config.get(key)) is not int or not 0 < config[key] <= 2**31 - 1
           for key in ("num_hidden_layers", "num_key_value_heads", "head_dim", "max_position_embeddings") if key in config):
        unknowns.append("Declared cache dimensions/context are outside the supported metadata range.")
    if model.deletion_status == "deleting":
        blockers.append("This installation is being deleted.")
    if model.is_local and not model.files_complete:
        blockers.append(model.problem or "Required model files are missing.")
    if not model.is_local:
        reasons.append("This candidate is not installed; download and validate its required files before selecting it.")
    if model.inference_status == "unknown":
        unknowns.append(model.problem or "Inference prerequisites have not been established.")
    if model.inference_status == "runtime_unavailable":
        blockers.append(model.problem or "The required inference runtime is unavailable.")
    if runtime.get("backend") == "mock":
        blockers.append("The active mock worker does not run model inference.")
    elif runtime.get("backend") != "native":
        unknowns.append("The active worker does not confirm local native/audio.cpp placement.")
    if backend == "audiocpp":
        if not runtime.get("audiocpp_available"):
            blockers.append("Install the audio.cpp CLI to run GGUF models.")
        if offload_ar or compute_backend != "torch":
            blockers.append("This audio.cpp adapter does not expose AR offload or native compute-backend selection.")
        reasons.append("The current audio.cpp adapter uses the package's bundled F16 VAE.")
    elif backend == "native":
        if not runtime.get("native_available"):
            unknowns.append("The worker has not confirmed the native YuE2 runtime.")
        bf16 = device.get("bf16_supported")
        if bf16 is False:
            blockers.append("The native loader requires BF16 eligibility on the selected GPU.")
        elif bf16 is None:
            unknowns.append("BF16 eligibility on this GPU is unconfirmed.")
        if compute_backend == "vllm":
            unknowns.append("vLLM placement/cache policy needs a separate measured memory profile; this estimate is for torch.")
        if vae and vae.parameter_count is not None and not _number(vae.parameter_count):
            unknowns.append("Declared VAE parameter count is outside the supported metadata range.")
        if vae and (vae.validation_status == "failed" or vae.compatibility_status == "incompatible"
                    or vae.format != "safetensors" or vae.backend != "native"):
            blockers.append("The selected VAE failed compatibility/validation checks.")
        elif not vae or not vae.inference_ready:
            unknowns.append("Select/install an inference-ready native VAE.")
        elif (model.path or model_config is not None) and vae.path:
            try:
                error = vae_config_compatibility_error(config, read_json_object(Path(vae.path) / "config.json"))
                if error:
                    blockers.append(error)
            except (OSError, ValueError):
                unknowns.append("The selected model/VAE configurations cannot be compared.")
        if offload_ar:
            reasons.append("AR offload is available during synthesis but still requires the full model load; no VRAM discount is assumed.")
    if not device.get("selectable") or device.get("cuda_available") is not True:
        unknowns.append("Worker CUDA availability/device selection is unconfirmed.")
    if loaded and device.get("worker_busy"):
        unknowns.append("This model is in use; current allocator counters cannot establish incremental generation headroom.")
    safe = capacity["usable_bytes"]
    if backend == "native" and safe is not None:
        # yue2-infer reserves 2 GiB before applying the per-process allocator cap.
        safe = min(safe, max(0, math.floor((memory_budget_gib - 2) * GIB)))
    peak = estimate["estimated_peak_bytes"]
    conservative_peak = estimate["conservative_peak_bytes"]
    excess = max(0, peak - safe) if peak is not None and safe is not None else None
    if peak is None:
        unknowns.append("Model weight size is unknown; parameter counts are not inferred from filenames.")
    if safe is None:
        unknowns.append("Usable GPU memory is unknown.")
    if excess:
        reasons.append(f"Estimated runtime VRAM exceeds the safe budget by {excess / GIB:.2f} GiB.")
    available_ram = _number(ram.get("available_bytes"))
    ram_required = estimate["estimated_system_ram_bytes"]
    ram_short = available_ram is not None and ram_required is not None and ram_required > available_ram
    if available_ram is None:
        reasons.append("Available host RAM is unknown; loading/offload headroom is unconfirmed.")
    elif ram_short:
        reasons.append("Estimated loading/offload RAM exceeds currently available host memory.")
    high_utilisation = (device.get("utilisation_percent") or 0) >= 80
    if high_utilisation:
        reasons.append("Current GPU utilization is high; competing workloads can change available headroom.")
    validated = model.validation_status == "validated" and (backend == "audiocpp" or (vae and vae.validation_status == "validated"))
    if not validated:
        reasons.append("Structural model/VAE validation is required before treating this estimate as a recommended installation.")
    if blockers:
        status = "cannot_run"
    elif unknowns:
        status = "unknown"
    elif excess:
        status = "not_recommended" if peak <= capacity["available_bytes"] else "cannot_run"
    elif ram_short or high_utilisation:
        status = "not_recommended"
    elif not validated or available_ram is None:
        status = "possibly_supported"
    elif conservative_peak > safe:
        status = "supported"
    else:
        same_vae = backend == "audiocpp" or (vae and device.get("loaded_vae") in [vae.id, *vae.aliases])
        status = "ready" if loaded and same_vae and model.inference_ready else "recommended"
    if not blockers and not unknowns and not excess:
        reasons.append("Estimated runtime VRAM fits the configured safe budget; this is not a guarantee.")
    if capacity["reclaimable_bytes"]:
        reasons.append("This budget requires unloading the current idle model first.")
    return dict(id=model.id, aliases=model.aliases, registry_id=model.registry_id, label=model.label, repo_id=model.huggingface_repo,
                filename=model.filename, format=model.format, backend=backend,
                quantization=model.quantization, precision=model.precision, architecture=model.architecture,
                model_bytes=model.bytes, parameters=model.parameter_count, inference_ready=model.inference_ready,
                currently_loaded=loaded, vae_id=vae.id if backend == "native" and vae else None,
                offload_supported=backend == "native", offload_requested=offload_ar,
                device_index=device["index"], status=status, reasons=blockers + unknowns + reasons,
                estimate=estimate, safe_budget_bytes=safe, excess_bytes=excess,
                # Legacy projection: fitting memory alone never makes this true.
                runnable=model.inference_ready and status in {"ready", "recommended", "supported"},
                peak_bytes=peak, required_bytes=peak + capacity["safety_margin_bytes"] if peak is not None and safe is not None else None)


def sort_recommendations(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: (STATUS_ORDER[item["status"]],
                                          item["estimate"]["estimated_peak_bytes"] or math.inf,
                                          item["id"]))
