"""System information, GPU selection and pre-flight risk estimates."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from yue2_studio_core.errors import ValidationError
from yue2_studio_core.store import Store

from app.core.deps import store_provider, system_info_provider
from app.services.system_info import SystemInfoService

router = APIRouter(prefix="/system", tags=["system"])


class DeviceSelection(BaseModel):
    device_index: int = Field(ge=0, le=31, description="Index of the CUDA device the worker should use")


@router.get("/info")
def info(system: SystemInfoService = Depends(system_info_provider)) -> dict:
    return system.info()


@router.get("/gpus")
def gpus(system: SystemInfoService = Depends(system_info_provider)) -> dict:
    """Devices the worker can use, and which one is selected.

    The list the worker reports is authoritative, because CUDA_VISIBLE_DEVICES
    can hide devices from it that NVML still sees from the API process.
    """
    return system.devices()


@router.get("/model-recommendation")
def model_recommendation(
    system: SystemInfoService = Depends(system_info_provider),
    device_index: int | None = Query(None, ge=0, le=31),
    vae: str = "standard",
    offload_ar: bool = False,
    compute_backend: Literal["torch", "torch-eager", "vllm"] = "torch",
    budget_gib: float = Query(40.0, ge=8, le=512),
) -> dict:
    return system.model_recommendation(device_index=device_index, vae=vae, offload_ar=offload_ar,
                                       compute_backend=compute_backend, memory_budget_gib=budget_gib)


@router.put("/device")
def select_device(
    payload: DeviceSelection,
    system: SystemInfoService = Depends(system_info_provider),
    store: Store = Depends(store_provider),
) -> dict:
    """Choose which GPU the worker runs the model on.

    The change is written to the data directory, so the worker picks it up on
    its next job without a restart. A job already running is not disturbed: it
    finishes on the device it started on.
    """
    available = system.devices()
    indices = {device["index"] for device in available["devices"] if device.get("selectable", True)}
    if not indices:
        raise ValidationError("Start the GPU worker before selecting a device; physical GPU indices may differ from CUDA indices.")
    if indices and payload.device_index not in indices:
        raise ValidationError(
            f"GPU {payload.device_index} is not available. Present: {sorted(indices)}.",
            details={"available": sorted(indices)},
        )
    store.write_runtime_settings({"device_index": payload.device_index})
    return system.devices()


@router.get("/vram-estimate")
def vram_estimate(
    seconds: float = Query(..., gt=0, allow_inf_nan=False),
    decoder_mode: str = Query("tiled", pattern="^(tiled|full)$"),
    budget_gib: float = Query(40.0, gt=0, allow_inf_nan=False),
    model: str = "default",
    vae: str = "standard",
    offload_ar: bool = False,
    compute_backend: Literal["torch", "torch-eager", "vllm"] = "torch",
    system: SystemInfoService = Depends(system_info_provider),
) -> dict:
    risk = system.vram_risk(seconds, decoder_mode, budget_gib, model=model, vae=vae,
                            offload_ar=offload_ar, compute_backend=compute_backend)
    return {"warning": risk}
