"""Generation lifecycle: create, inspect, cancel, retry, duplicate."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from yue2_studio_core.store import Store

from app.core.deps import generation_service_provider, store_provider
from app.services.generations import GenerationService

router = APIRouter(tags=["generations"])


class GenerationCreate(BaseModel):
    """A partial configuration merged over configs/yue2.defaults.json."""

    project_id: str | None = None
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    priority: int = 0
    config: dict[str, Any] = Field(default_factory=dict)


class GenerationPatch(BaseModel):
    title: str | None = None
    favorite: bool | None = None


@router.post("/generations", status_code=201)
def create_generation(
    payload: GenerationCreate,
    service: GenerationService = Depends(generation_service_provider),
) -> dict:
    job, project, warnings = service.create_generation(
        overrides=payload.config,
        project_id=payload.project_id,
        title=payload.title,
        tags=payload.tags,
        priority=payload.priority,
    )
    return {
        "generation": job.model_dump(mode="json"),
        "project": project.model_dump(mode="json"),
        "warnings": warnings,
    }


@router.get("/generations")
def list_generations(
    project_id: str | None = None,
    status: list[str] | None = Query(None),
    mode: str | None = None,
    search: str | None = None,
    favorite: bool | None = None,
    min_duration: float | None = None,
    max_duration: float | None = None,
    model: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: GenerationService = Depends(generation_service_provider),
) -> dict:
    result = service.list_generations(
        project_id=project_id,
        status=status,
        mode=mode,
        search=search,
        favorite=favorite,
        min_duration=min_duration,
        max_duration=max_duration,
        model=model,
        limit=limit,
        offset=offset,
    )
    result["items"] = [job.model_dump(mode="json") for job in result["items"]]
    return result


@router.get("/generations/{generation_id}")
def get_generation(generation_id: str, store: Store = Depends(store_provider)) -> dict:
    job = store.get_job(generation_id)
    project = store.get_project(job.project_id)
    return {"generation": job.model_dump(mode="json"), "project": project.model_dump(mode="json")}


@router.patch("/generations/{generation_id}")
def patch_generation(
    generation_id: str,
    payload: GenerationPatch,
    service: GenerationService = Depends(generation_service_provider),
) -> dict:
    job = None
    if payload.title is not None:
        job = service.rename(generation_id, payload.title)
    if payload.favorite is not None:
        job = service.set_favorite(generation_id, payload.favorite)
    if job is None:
        job = service.store.get_job(generation_id)
    return job.model_dump(mode="json")


@router.delete("/generations/{generation_id}")
def delete_generation(
    generation_id: str, service: GenerationService = Depends(generation_service_provider)
) -> dict:
    """Delete a generation and its artifacts.

    Returns what was actually removed. ``complete: false`` means some files
    could not be deleted and are named in ``failures`` — the caller is told
    rather than left with silent orphans.
    """
    return service.delete(generation_id)


@router.post("/generations/{generation_id}/cancel")
def cancel_generation(
    generation_id: str, service: GenerationService = Depends(generation_service_provider)
) -> dict:
    return service.cancel(generation_id).model_dump(mode="json")


@router.post("/generations/{generation_id}/retry", status_code=201)
def retry_generation(
    generation_id: str, service: GenerationService = Depends(generation_service_provider)
) -> dict:
    return service.retry(generation_id).model_dump(mode="json")


@router.post("/generations/{generation_id}/duplicate", status_code=201)
def duplicate_generation(
    generation_id: str,
    overrides: dict[str, Any] = Body(default_factory=dict),
    service: GenerationService = Depends(generation_service_provider),
) -> dict:
    return service.duplicate(generation_id, overrides).model_dump(mode="json")


@router.get("/generations/{generation_id}/manifest")
def generation_manifest(
    generation_id: str, service: GenerationService = Depends(generation_service_provider)
) -> dict:
    return service.manifest(generation_id)


@router.get("/generations/{generation_id}/log")
def generation_log(
    generation_id: str,
    limit: int = Query(500, ge=1, le=5000),
    store: Store = Depends(store_provider),
) -> dict:
    job = store.get_job(generation_id)
    return {"items": store.read_log(job, limit)}


@router.get("/queue")
def queue_view(service: GenerationService = Depends(generation_service_provider)) -> dict:
    return service.queue_view()
