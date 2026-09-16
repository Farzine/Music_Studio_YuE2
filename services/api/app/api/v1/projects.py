"""Projects: the container a song and its generations belong to."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from yue2_studio_core.models import GenerationMode, SongProject
from yue2_studio_core.store import Store

from app.core.deps import project_service_provider, store_provider
from app.services.projects import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    title: str = ""
    description: str = ""
    style: str = ""
    lyrics: str = ""
    mode: GenerationMode = GenerationMode.FULL
    tags: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    """Metadata only. Generation settings go through ``PUT /{id}/config``."""

    title: str | None = None
    description: str | None = None
    style: str | None = None
    lyrics: str | None = None
    mode: GenerationMode | None = None
    tags: list[str] | None = None
    favorite: bool | None = None


class ProjectConfigUpdate(BaseModel):
    """A partial configuration merged over configs/yue2.defaults.json."""

    config: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_projects(
    store: Store = Depends(store_provider),
    projects: ProjectService = Depends(project_service_provider),
) -> dict:
    """Every project with the counts the list view shows.

    The summary is computed here rather than in the browser so the list does
    not have to fetch each project's generations to render a card.
    """
    items = []
    for project in store.list_projects():
        takes = projects.generations(project.id)
        audio = [job for job in takes if job.status.produced_audio]
        items.append(
            {
                **project.model_dump(mode="json"),
                "generation_count": len(takes),
                "playable_count": len(audio),
                "latest_generation_id": takes[0].id if takes else None,
                "latest_generation_at": takes[0].requested_at.isoformat() if takes else None,
            }
        )
    return {"items": items}


@router.post("", status_code=201)
def create_project(payload: ProjectCreate, store: Store = Depends(store_provider)) -> dict:
    project = store.create_project(**payload.model_dump())
    return project.model_dump(mode="json")


@router.get("/{project_id}")
def get_project(
    project_id: str,
    store: Store = Depends(store_provider),
    projects: ProjectService = Depends(project_service_provider),
) -> dict:
    project: SongProject = store.get_project(project_id)
    takes = projects.generations(project_id)
    return {
        "project": project.model_dump(mode="json"),
        "generations": [job.model_dump(mode="json") for job in takes],
    }


@router.patch("/{project_id}")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    projects: ProjectService = Depends(project_service_provider),
) -> dict:
    fields = payload.model_dump(exclude_none=True)
    return projects.update_metadata(project_id, fields).model_dump(mode="json")


@router.get("/{project_id}/config")
def get_project_config(
    project_id: str, projects: ProjectService = Depends(project_service_provider)
) -> dict:
    """The configuration the settings editor opens with, and where it came from."""
    config, source = projects.starting_config(project_id)
    return {"config": config.model_dump(mode="json"), "source": source}


@router.put("/{project_id}/config")
def put_project_config(
    project_id: str,
    payload: ProjectConfigUpdate,
    projects: ProjectService = Depends(project_service_provider),
) -> dict:
    """Store the settings new takes start from.

    Takes already made are untouched: each one keeps the snapshot it ran with.
    """
    project = projects.update_settings(project_id, payload.config)
    return project.model_dump(mode="json")


@router.delete("/{project_id}")
def delete_project(
    project_id: str, projects: ProjectService = Depends(project_service_provider)
) -> dict:
    """Delete a project and every generation in it.

    Returns what was actually removed. ``complete: false`` means some files
    survived and are named in ``failures``, rather than reporting a clean
    delete over leftovers nobody would look for.
    """
    return projects.delete(project_id)
