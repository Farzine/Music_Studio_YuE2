"""Presets: built-in and user-saved configurations."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from yue2_studio_core.errors import ConflictError, NotFoundError
from yue2_studio_core.ids import new_id
from yue2_studio_core.models import Preset
from yue2_studio_core.parameters import builtin_presets, config_from_overrides, default_config
from yue2_studio_core.store import Store

from app.core.deps import store_provider

router = APIRouter(prefix="/presets", tags=["presets"])


class PresetCreate(BaseModel):
    name: str
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_presets(store: Store = Depends(store_provider)) -> dict:
    items = [preset.model_dump(mode="json") for preset in builtin_presets()]
    items += [preset.model_dump(mode="json") for preset in store.list_user_presets()]
    return {"items": items, "defaults": default_config().model_dump(mode="json")}


@router.post("", status_code=201)
def create_preset(payload: PresetCreate, store: Store = Depends(store_provider)) -> dict:
    preset = Preset(
        id=new_id("pre"),
        name=payload.name,
        description=payload.description,
        builtin=False,
        config=config_from_overrides(payload.config),
    )
    return store.save_preset(preset).model_dump(mode="json")


@router.put("/{preset_id}")
def update_preset(preset_id: str, payload: PresetCreate, store: Store = Depends(store_provider)) -> dict:
    existing = {preset.id for preset in builtin_presets()}
    if preset_id in existing:
        raise ConflictError("Built-in presets cannot be modified. Save a copy instead.")
    presets = {preset.id: preset for preset in store.list_user_presets()}
    if preset_id not in presets:
        raise NotFoundError(f"preset {preset_id} not found")
    preset = presets[preset_id]
    preset.name = payload.name
    preset.description = payload.description
    preset.config = config_from_overrides(payload.config)
    return store.save_preset(preset).model_dump(mode="json")


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: str, store: Store = Depends(store_provider)) -> None:
    if preset_id in {preset.id for preset in builtin_presets()}:
        raise ConflictError("Built-in presets cannot be deleted.")
    store.delete_preset(preset_id)
