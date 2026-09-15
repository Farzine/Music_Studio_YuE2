"""Model inventory, backend capabilities and the generation form schema."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import capability_provider
from app.services.capabilities import CapabilityService

router = APIRouter(tags=["models"])


@router.get("/models")
def list_models(capabilities: CapabilityService = Depends(capability_provider)) -> dict:
    return {"items": capabilities.local_models()}


@router.get("/models/capabilities")
def model_capabilities(
    backend: str | None = Query(None),
    capabilities: CapabilityService = Depends(capability_provider),
) -> dict:
    return capabilities.capabilities(backend)


@router.get("/generation/schema")
def generation_schema(
    backend: str | None = Query(None),
    capabilities: CapabilityService = Depends(capability_provider),
) -> dict:
    return capabilities.schema(backend)


@router.get("/generation/workflow-mapping")
def workflow_mapping() -> dict:
    """The ComfyUI reference mapping, for the technical-details drawer."""
    from yue2_studio_core.parameters import load_workflow_mapping

    return load_workflow_mapping()
