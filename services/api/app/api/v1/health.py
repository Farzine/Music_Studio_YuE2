"""Liveness and a short readiness summary."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import capability_provider, settings_provider, system_info_provider
from app.services.capabilities import CapabilityService
from app.services.system_info import SystemInfoService

router = APIRouter(tags=["system"])


@router.get("/health")
def health(
    settings=Depends(settings_provider),
    capabilities: CapabilityService = Depends(capability_provider),
    system: SystemInfoService = Depends(system_info_provider),
) -> dict:
    probe = capabilities.runtime_probe()
    worker = system.worker_state()
    models = capabilities.local_models()
    vae_ready = any(model["role"] == "vae" and model["is_default"] and model["inference_ready"]
                    for model in models)
    ready = worker["online"] and any(
        model["role"] == "model" and model["inference_ready"]
        and (model["format"] == "gguf" or vae_ready) for model in models
    )
    return {
        "status": "ok",
        "ready": ready,
        "backend": settings.yue2_backend,
        "model_present": probe["model_present"],
        "vae_present": probe["vae_present"],
        "worker_online": worker["online"],
    }
