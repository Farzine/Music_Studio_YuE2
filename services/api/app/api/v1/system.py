"""System information, GPU selection and pre-flight risk estimates."""
from __future__ import annotations

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
    indices = {device["index"] for device in available["devices"]}
    if indices and payload.device_index not in indices:
        raise ValidationError(
            f"GPU {payload.device_index} is not available. Present: {sorted(indices)}.",
            details={"available": sorted(indices)},
        )
    store.write_runtime_settings({"device_index": payload.device_index})
    return system.devices()


@router.get("/vram-estimate")
def vram_estimate(
    seconds: float = Query(..., gt=0),
    decoder_mode: str = Query("tiled", pattern="^(tiled|full)$"),
    budget_gib: float = Query(40.0, gt=0),
    system: SystemInfoService = Depends(system_info_provider),
) -> dict:
    risk = system.vram_risk(seconds, decoder_mode, budget_gib)
    return {"warning": risk}
