"""Model inventory, backend capabilities, the form schema and token budgeting."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query

from app.core.deps import budget_provider, capability_provider
from app.services.budget import BudgetService
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


@router.post("/generation/estimate")
def estimate_budget(
    payload: dict[str, Any] = Body(default_factory=dict),
    budget: BudgetService = Depends(budget_provider),
) -> dict:
    """Token budget for a request, before anything is queued.

    Takes the same partial configuration a generation does, so the answer is
    for exactly what would be submitted. Counting uses the checkpoint's own
    tokenizer, and the reply says so; when that tokenizer cannot be loaded the
    figures are marked inexact rather than presented as fact.
    """
    from yue2_studio_core.parameters import config_from_overrides

    config = config_from_overrides(payload.get("config", payload))
    estimate = budget.estimate(config)
    limits = budget.limits(config)
    return {"estimate": estimate.to_dict(), "limits": limits.to_dict()}


@router.get("/generation/limits")
def generation_limits(budget: BudgetService = Depends(budget_provider)) -> dict:
    """The active checkpoint's own limits, and where each number came from."""
    return budget.limits().to_dict()


@router.get("/generation/workflow-mapping")
def workflow_mapping() -> dict:
    """The ComfyUI reference mapping, for the technical-details drawer."""
    from yue2_studio_core.parameters import load_workflow_mapping

    return load_workflow_mapping()
