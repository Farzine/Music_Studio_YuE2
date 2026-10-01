"""Model inventory, backend capabilities, the form schema and token budgeting."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query
from pydantic import BaseModel
from yue2_studio_core.models import GenerationConfig

from app.core.deps import budget_provider, capability_provider, model_downloads_provider, model_service_provider, system_info_provider
from app.services.budget import BudgetService
from app.services.capabilities import CapabilityService
from app.services.model_downloads import ModelDownloads
from app.services.models import ModelService
from app.services.system_info import SystemInfoService

router = APIRouter(tags=["models"])


class DownloadRequest(BaseModel):
    repo_id: str
    filename: str
    revision: str | None = None
    mode: Literal["single", "selected", "repository"] = "single"
    selected_files: list[str] | None = None


class InspectHubRequest(BaseModel):
    repo_id: str
    revision: str | None = None
    device_index: int | None = None


class PreviewHubRequest(InspectHubRequest):
    filename: str
    mode: Literal["single", "selected", "repository"] = "single"
    selected_files: list[str] | None = None


def _assess_inspection(inspection: dict, system: SystemInfoService, capabilities: CapabilityService,
                       device_index: int | None) -> dict:
    contexts = inspection.pop("candidate_contexts")
    ids = {c["model"]["id"] for c in inspection["candidates"]}
    result = system.model_recommendation(
        device_index=device_index,
        entries=[*capabilities.local_models(), *(c["model"] for c in inspection["candidates"])],
        candidate_contexts=contexts,
    )
    return {**inspection, "device_index": result["device_index"],
            "assessments": [a for a in result["items"] if a["id"] in ids],
            "by_gpu": [{"device_index": g["device_index"], "items": [a for a in g["items"] if a["id"] in ids]}
                       for g in result["by_gpu"]]}


@router.post("/models/hub/inspect")
def inspect_hub(
    payload: InspectHubRequest,
    downloads: ModelDownloads = Depends(model_downloads_provider),
    system: SystemInfoService = Depends(system_info_provider),
    capabilities: CapabilityService = Depends(capability_provider),
) -> dict:
    return _assess_inspection(downloads.hub.inspect(payload.repo_id, payload.revision), system, capabilities, payload.device_index)


@router.post("/models/hub/preview")
def preview_hub(
    payload: PreviewHubRequest,
    downloads: ModelDownloads = Depends(model_downloads_provider),
    system: SystemInfoService = Depends(system_info_provider),
    capabilities: CapabilityService = Depends(capability_provider),
) -> dict:
    inspection = downloads.hub.inspect(payload.repo_id, payload.revision)
    preview = downloads.hub.preview(inspection, payload.filename, mode=payload.mode, selected_files=payload.selected_files)
    assessment = _assess_inspection(inspection, system, capabilities, payload.device_index)
    model_id = preview["candidate"]["model"]["id"]
    return {**preview, "device_index": assessment["device_index"],
            "assessment": next((a for a in assessment["assessments"] if a["id"] == model_id), None)}


@router.get("/models/hub/discover")
def discover_hub(
    base_model: str = "m-a-p/YuE2-3B", limit: int = Query(10, ge=1, le=20), device_index: int | None = None,
    downloads: ModelDownloads = Depends(model_downloads_provider),
    system: SystemInfoService = Depends(system_info_provider),
    capabilities: CapabilityService = Depends(capability_provider),
) -> dict:
    result = downloads.hub.discover(base_model, limit)
    result["items"] = [(_assess_inspection(item, system, capabilities, device_index) if "error" not in item
                        else {k: v for k, v in item.items() if k != "candidate_contexts"}) for item in result["items"]]
    return result


@router.get("/models/hub")
def browse_hub(
    repo_id: str,
    revision: str | None = None,
    downloads: ModelDownloads = Depends(model_downloads_provider),
) -> dict:
    return downloads.browse(repo_id, revision)


@router.get("/models/downloads")
def list_downloads(downloads: ModelDownloads = Depends(model_downloads_provider)) -> dict:
    return {"items": downloads.list()}


@router.get("/models/downloads/{download_id}")
def download_status(download_id: str, downloads: ModelDownloads = Depends(model_downloads_provider)) -> dict:
    return downloads.get(download_id)


@router.post("/models/downloads", status_code=202)
def download_model(
    payload: DownloadRequest,
    background: BackgroundTasks,
    downloads: ModelDownloads = Depends(model_downloads_provider),
) -> dict:
    job = downloads.start(payload.repo_id, payload.filename, payload.revision,
                          mode=payload.mode, selected_files=payload.selected_files)
    background.add_task(downloads.run, job["id"])
    return job


@router.post("/models/downloads/{download_id}/retry", status_code=202)
def retry_download(download_id: str, background: BackgroundTasks,
                   downloads: ModelDownloads = Depends(model_downloads_provider)) -> dict:
    job = downloads.retry(download_id)
    background.add_task(downloads.run, job["id"])
    return job


@router.delete("/models/downloads/{download_id}/partial")
def cleanup_download(download_id: str, downloads: ModelDownloads = Depends(model_downloads_provider)) -> dict:
    return downloads.cleanup(download_id)


@router.get("/models")
def list_models(capabilities: CapabilityService = Depends(capability_provider)) -> dict:
    return {"items": capabilities.local_models()}


@router.get("/models/capabilities")
def model_capabilities(
    backend: str | None = Query(None),
    capabilities: CapabilityService = Depends(capability_provider),
) -> dict:
    return capabilities.capabilities(backend)


class ValidateRequest(BaseModel):
    verify_checksum: bool = False


class DeleteRequest(BaseModel):
    confirmation_token: str
    confirmed_path: str


class LoadRequest(BaseModel):
    config: GenerationConfig | None = None


@router.get("/models/runtime-commands/{command_id}")
def runtime_command(command_id: str, models: ModelService = Depends(model_service_provider),
                    system: SystemInfoService = Depends(system_info_provider)) -> dict:
    return models.runtime_command(command_id, system.worker_state())


@router.post("/models/{registry_id}/load", status_code=202)
def load_model(registry_id: str, payload: LoadRequest = Body(default=LoadRequest()),
               models: ModelService = Depends(model_service_provider), system: SystemInfoService = Depends(system_info_provider)) -> dict:
    return models.request_runtime(registry_id, "load", system.worker_state(), payload.config)


@router.post("/models/{registry_id}/unload", status_code=202)
def unload_model(registry_id: str, models: ModelService = Depends(model_service_provider),
                 system: SystemInfoService = Depends(system_info_provider)) -> dict:
    return models.request_runtime(registry_id, "unload", system.worker_state())


@router.get("/models/{registry_id}")
def inspect_model(registry_id: str, models: ModelService = Depends(model_service_provider)) -> dict:
    return models.inspect(registry_id)


@router.post("/models/{registry_id}/validate")
def validate_model(registry_id: str, payload: ValidateRequest, models: ModelService = Depends(model_service_provider)) -> dict:
    return models.validate(registry_id, verify_checksum=payload.verify_checksum)


@router.get("/models/{registry_id}/deletion-preview")
def deletion_preview(registry_id: str, models: ModelService = Depends(model_service_provider)) -> dict:
    return models.preview(registry_id)


@router.delete("/models/{registry_id}")
def delete_model(registry_id: str, payload: DeleteRequest, models: ModelService = Depends(model_service_provider)) -> dict:
    return models.delete(registry_id, **payload.model_dump())


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
