"""Task choices and admission device checks; no model loading or CUDA imports."""
from pathlib import Path

from yue2_studio_core.errors import ValidationError
from yue2_studio_core.model_metadata import GGUF_COMPANIONS, resolve_model_reference, resolve_vae_reference, selected_vae_error
from yue2_studio_core.models import GenerationConfig
from yue2_studio_core.queue import FilesystemJobQueue

from app.services.system_info import SystemInfoService


def validate_task_device(index, settings, store) -> None:
    if index is None:
        return  # legacy tasks follow the selected worker device at claim time
    if settings.yue2_backend != "native":
        raise ValidationError("This backend manages its own device; select the backend-managed runtime option.")
    system = SystemInfoService(settings, store, FilesystemJobQueue(store))
    inventory = system.devices()
    if not any(d["index"] == index and d.get("selectable") and d.get("cuda_available") for d in inventory["devices"]):
        raise ValidationError(f"GPU {index} is unavailable to the worker. Start the worker, refresh hardware, and choose a visible CUDA device.",
                              details={"parameter": "model.device_index"})


def task_options(config: GenerationConfig, capabilities, system: SystemInfoService) -> dict:
    entries = capabilities.local_models()
    settings = capabilities.settings
    inventory = system.devices()
    model_ref = resolve_model_reference(config.model.checkpoint, settings)
    selected = next((e for e in entries if e["role"] == "model" and model_ref in [e["id"], *e["aliases"]]), None)
    index = config.model.device_index if config.model.device_index is not None else inventory["selected_index"]
    gpu_options = ([{"value": None, "label": f"{settings.yue2_backend} runtime (device managed by backend)", "enabled": True, "disabled_reason": None}]
                   if settings.yue2_backend != "native" else
                   [{"value": d["index"], "label": f'GPU {d["index"]} · {d.get("name") or "Unknown"}',
                     "enabled": bool(d.get("selectable") and d.get("cuda_available")),
                     "disabled_reason": None if d.get("selectable") and d.get("cuda_available") else "Unavailable to the worker"}
                    for d in inventory["devices"]])
    assessments = {}
    if settings.yue2_backend == "native" and any(d["index"] == index for d in inventory["devices"]):
        result = system.model_recommendation(device_index=index, entries=entries, vae=config.model.vae,
                                            compute_backend=config.model.compute_backend, offload_ar=config.model.offload_ar,
                                            memory_budget_gib=config.model.memory_budget_gib)
        assessments = {a["id"]: a for a in result["items"]}
    models = []
    for entry in entries:
        if entry["role"] != "model":
            continue
        assessment = assessments.get(entry["id"])
        reason = entry["problem"] if not entry["inference_ready"] else None
        if entry["format"] == "gguf" and settings.yue2_backend != "native":
            reason = "Requires the local native audio.cpp worker."
        if assessment and assessment["status"] == "cannot_run":
            reason = " ".join(assessment["reasons"])
        option = {"value": entry["id"], "label": entry["label"], "enabled": reason is None and entry["inference_ready"],
                  "disabled_reason": reason, "format": entry["format"], "assessment": assessment, "bytes": entry["bytes"]}
        models.append(option)
        if entry["is_default"]:
            models.append({**option, "value": "default", "label": "Default — " + entry["label"]})
    rank = {state: i for i, state in enumerate(("ready", "recommended", "supported", "possibly_supported", "unknown", "not_recommended", "cannot_run"))}
    models.sort(key=lambda m: (not m["enabled"], rank.get((m["assessment"] or {}).get("status"), 4), m["value"]))
    vaes = []
    bundled = selected and selected["format"] == "gguf"
    if bundled:
        path = str(Path(selected["id"]) / GGUF_COMPANIONS[0])
        for value in ("standard", path):
            vaes.append({"value": value, "label": "Bundled YuE2 F16 VAE" + (" (standard alias)" if value == "standard" else ""),
                         "enabled": value != "standard" and selected["inference_ready"],
                         "disabled_reason": "Select the package's bundled F16 VAE explicitly; your previous VAE choice is preserved." if value == "standard" else selected["problem"]})
    else:
        for entry in entries:
            if entry["role"] != "vae":
                continue
            reason = selected_vae_error(selected, entry["id"], settings, entry) if selected else "Choose an inference model first."
            values = [entry["id"]]
            for alias in ("standard", "legacy"):
                if resolve_vae_reference(alias, settings) in [entry["id"], *entry["aliases"]]:
                    values.append(alias)
            for value in values:
                vaes.append({"value": value, "label": entry["label"] + (f" ({value})" if value in {"standard", "legacy"} else ""),
                             "enabled": reason is None, "disabled_reason": reason})
    issues = []
    for label, value, options in (("Model", config.model.checkpoint, models), ("VAE", config.model.vae, vaes),
                                   ("GPU", config.model.device_index if settings.yue2_backend != "native" else index, gpu_options)):
        option = next((o for o in options if o["value"] == value), None)
        if not option or not option["enabled"]:
            issues.append((option or {}).get("disabled_reason") or f"Choose an available {label}.")
    return {"models": models, "vaes": vaes, "gpus": gpu_options, "selected_device_index": inventory["selected_index"],
            "backend": settings.yue2_backend, "issues": issues, "valid": not issues,
            "vae_requirement": "Bundled F16 VAE required" if bundled else "Compatible native VAE required"}
