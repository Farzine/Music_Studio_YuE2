"""Model residency: what forces a reload, and what must not.

Reloading the 7.26 GB checkpoint for a sampling tweak would be wasteful; worse,
keeping sampling on the resident pipeline once let a previous job's token budget
leak into the next one. Sampling therefore travels with the request and is
deliberately absent from the pipeline key.
"""
from __future__ import annotations

import pytest

from yue2_studio_core.parameters import config_from_overrides

pytest.importorskip("yue2", reason="the worker environment is not active")

from services.yue2_worker.model_manager.manager import ModelManager  # noqa: E402


@pytest.fixture()
def manager(data_dir):
    from yue2_studio_core.settings import get_settings

    return ModelManager(get_settings())


def test_sampling_changes_do_not_change_the_pipeline_key(manager, data_dir):
    base = config_from_overrides({"prompt": {"style": "s", "lyrics": "[Verse]\nl"}})
    tweaked = config_from_overrides(
        {
            "prompt": {"style": "s", "lyrics": "[Verse]\nl"},
            "sampling": {"temperature": 0.8, "top_k": 40, "max_duration_seconds": 30.0},
            "planner": {"temperature": 0.5, "max_tokens": 2048},
        }
    )
    assert manager.key_for(base) == manager.key_for(tweaked)


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": {"memory_budget_gib": 24.0}},
        {"model": {"offload_ar": True}},
        {"model": {"compute_backend": "torch-eager"}},
        {"model": {"vae": "legacy"}},
        {"decoder": {"tile_frames": 512}},
        {"synthesis": {"ode_steps": 64}},
    ],
)
def test_pipeline_level_settings_do_force_a_reload(manager, data_dir, overrides):
    base = config_from_overrides({"prompt": {"style": "s", "lyrics": "[Verse]\nl"}})
    changed = config_from_overrides({"prompt": {"style": "s", "lyrics": "[Verse]\nl"}, **overrides})
    assert manager.key_for(base) != manager.key_for(changed)


def test_request_sampling_carries_the_duration_budget(manager, data_dir):
    config = config_from_overrides({"sampling": {"max_duration_seconds": 20.0}})
    _, semantic = manager.native_sampling(config)
    # 20 s at 25 frames per second.
    assert semantic.max_tokens == 500
    assert semantic.temperature == config.sampling.temperature

    planner, _ = manager.native_sampling(config)
    assert planner.max_tokens == config.planner.max_tokens
    assert planner.temperature == config.planner.temperature


def test_a_missing_model_directory_fails_with_a_precise_code(manager, data_dir, monkeypatch):
    from yue2_studio_core.errors import ErrorCode, StudioError

    monkeypatch.setattr(manager, "resolve_model", lambda config: "/nonexistent/YuE2-3B")
    config = config_from_overrides({})
    with pytest.raises(StudioError) as excinfo:
        manager.verify_files(config)
    assert excinfo.value.code is ErrorCode.MODEL_NOT_FOUND
    assert excinfo.value.stage == "loading_model"
