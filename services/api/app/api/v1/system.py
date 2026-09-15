"""System information and pre-flight risk estimates."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import system_info_provider
from app.services.system_info import SystemInfoService

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info")
def info(system: SystemInfoService = Depends(system_info_provider)) -> dict:
    return system.info()


@router.get("/vram-estimate")
def vram_estimate(
    seconds: float = Query(..., gt=0),
    decoder_mode: str = Query("tiled", pattern="^(tiled|full)$"),
    budget_gib: float = Query(40.0, gt=0),
    system: SystemInfoService = Depends(system_info_provider),
) -> dict:
    risk = system.vram_risk(seconds, decoder_mode, budget_gib)
    return {"warning": risk}
