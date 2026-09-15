"""ABC score workspace: read, edit, validate, compare, regenerate."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from yue2_studio_core.abc import compare as compare_abc
from yue2_studio_core.abc import try_validate, validate as validate_abc
from yue2_studio_core.errors import NotFoundError
from yue2_studio_core.models import Score
from yue2_studio_core.store import Store

from app.core.deps import generation_service_provider, store_provider
from app.services.generations import GenerationService

router = APIRouter(prefix="/scores", tags=["scores"])


class ScoreUpdate(BaseModel):
    edited_abc: str


class AbcText(BaseModel):
    abc: str


class AbcComparison(BaseModel):
    before: str | None = None
    after: str
    voices: str = "both"
    allow_tempo_change: bool = False


@router.post("/validate")
def validate_text(payload: AbcText) -> dict:
    """Validate arbitrary ABC without attaching it to a generation."""
    ok, report, error = try_validate(payload.abc)
    return {"valid": ok, "report": report, "error": error}


@router.get("/{generation_id}")
def get_score(generation_id: str, store: Store = Depends(store_provider)) -> dict:
    score = store.get_score(generation_id)
    source_ok, source_report, source_error = try_validate(score.source_abc)
    edited_ok, edited_report, edited_error = (
        try_validate(score.edited_abc) if score.edited_abc else (None, None, None)
    )
    return {
        "score": score.model_dump(mode="json"),
        "source": {"valid": source_ok, "report": source_report, "error": source_error},
        "edited": {"valid": edited_ok, "report": edited_report, "error": edited_error},
    }


@router.put("/{generation_id}")
def save_edited_score(
    generation_id: str, payload: ScoreUpdate, store: Store = Depends(store_provider)
) -> dict:
    score = store.get_score(generation_id)
    validate_abc(payload.edited_abc)  # refuse to store a score the runtime would reject
    score.edited_abc = payload.edited_abc
    store.save_score(score)
    return {
        "score": score.model_dump(mode="json"),
        "comparison": compare_abc(score.source_abc, payload.edited_abc) if score.source_abc else None,
    }


@router.post("/{generation_id}/validate")
def validate_score(generation_id: str, store: Store = Depends(store_provider)) -> dict:
    score = store.get_score(generation_id)
    target = score.edited_abc or score.source_abc
    ok, report, error = try_validate(target)
    return {"valid": ok, "report": report, "error": error}


@router.post("/{generation_id}/compare")
def compare_score(
    generation_id: str, payload: AbcComparison, store: Store = Depends(store_provider)
) -> dict:
    score = store.get_score(generation_id)
    before = payload.before if payload.before is not None else score.source_abc
    if not before:
        raise NotFoundError("There is no source score to compare against.")
    return compare_abc(
        before,
        payload.after,
        voices=payload.voices,
        allow_tempo_change=payload.allow_tempo_change,
    )


@router.post("/{generation_id}/regenerate", status_code=201)
def regenerate_from_score(
    generation_id: str,
    overrides: dict[str, Any] = Body(default_factory=dict),
    store: Store = Depends(store_provider),
    service: GenerationService = Depends(generation_service_provider),
) -> dict:
    """Queue a new generation that uses the edited score as the planner input."""
    score = store.get_score(generation_id)
    abc = score.edited_abc or score.source_abc
    validate_abc(abc)
    merged = {"prompt": {"abc": abc, "mode": "score_edit"}}
    for key, value in overrides.items():
        if key == "prompt" and isinstance(value, dict):
            merged["prompt"].update(value)
            merged["prompt"]["abc"] = abc
        else:
            merged[key] = value
    job = service.duplicate(generation_id, merged)
    return job.model_dump(mode="json")
