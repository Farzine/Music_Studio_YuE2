"""Version 1 API surface."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    artifacts,
    events,
    generations,
    health,
    models,
    presets,
    projects,
    scores,
    system,
    uploads,
)

api_router = APIRouter(prefix="/api/v1")
for module in (health, system, models, projects, generations, artifacts, scores, presets, uploads):
    api_router.include_router(module.router)
api_router.include_router(events.router)
