"""Projects: the container a song and its generations belong to."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from yue2_studio_core.models import GenerationMode, SongProject
from yue2_studio_core.store import Store

from app.core.deps import generation_service_provider, store_provider
from app.services.generations import GenerationService

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    title: str = ""
    description: str = ""
    style: str = ""
    lyrics: str = ""
    mode: GenerationMode = GenerationMode.FULL
    tags: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    style: str | None = None
    lyrics: str | None = None
    mode: GenerationMode | None = None
    tags: list[str] | None = None
    favorite: bool | None = None


@router.get("")
def list_projects(store: Store = Depends(store_provider)) -> dict:
    return {"items": [project.model_dump(mode="json") for project in store.list_projects()]}


@router.post("", status_code=201)
def create_project(payload: ProjectCreate, store: Store = Depends(store_provider)) -> dict:
    project = store.create_project(**payload.model_dump())
    return project.model_dump(mode="json")


@router.get("/{project_id}")
def get_project(
    project_id: str,
    store: Store = Depends(store_provider),
    generations: GenerationService = Depends(generation_service_provider),
) -> dict:
    project: SongProject = store.get_project(project_id)
    listing = generations.list_generations(project_id=project_id, limit=500)
    return {
        "project": project.model_dump(mode="json"),
        "generations": [job.model_dump(mode="json") for job in listing["items"]],
    }


@router.patch("/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, store: Store = Depends(store_provider)) -> dict:
    project = store.get_project(project_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(project, key, value)
    return store.save_project(project).model_dump(mode="json")


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, store: Store = Depends(store_provider)) -> None:
    store.delete_project(project_id)
