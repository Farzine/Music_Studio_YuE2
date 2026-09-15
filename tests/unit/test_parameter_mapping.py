"""The parameter registry is the single source of truth for every setting."""
from __future__ import annotations

import json
from pathlib import Path

from yue2_studio_core.models import GenerationConfig
from yue2_studio_core.parameters import (
    default_config,
    describe_registry,
    get_path,
    load_registry,
    load_workflow_mapping,
    unsupported_parameters_in_use,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_registry_key_exists_on_the_domain_model(data_dir):
    config = default_config()
    for parameter in load_registry()["parameters"]:
        get_path(config, parameter["key"])  # raises AttributeError if it drifted


def test_registry_keys_are_unique(data_dir):
    keys = [parameter["key"] for parameter in load_registry()["parameters"]]
    assert len(keys) == len(set(keys))


def test_comfy_only_parameters_are_declared_unsupported_on_native(data_dir):
    unsupported = {
        parameter["key"]
        for parameter in load_registry()["parameters"]
        if not parameter["native"]["supported"]
    }
    assert unsupported == {
        "planner.seed",
        "synthesis.sampler_name",
        "synthesis.scheduler",
        "synthesis.denoise",
        "synthesis.seconds",
        "synthesis.batch_size",
    }
    for parameter in load_registry()["parameters"]:
        if not parameter["native"]["supported"]:
            # An unsupported parameter must say why, and name its ComfyUI home.
            assert parameter["native"]["note"]
            assert parameter["comfy"]["node"]


def test_setting_a_comfy_only_parameter_is_reported_not_dropped(data_dir):
    config = GenerationConfig.model_validate(
        {
            "prompt": {"style": "s", "lyrics": "l"},
            "synthesis": {"sampler_name": "dpm_2", "denoise": 0.8},
        }
    )
    violations = unsupported_parameters_in_use(config, "native")
    reported = {item["parameter"] for item in violations}
    assert reported == {"synthesis.sampler_name", "synthesis.denoise"}
    assert all(item["reason"] for item in violations)


def test_workflow_mapping_matches_the_reference_workflow(data_dir):
    mapping = load_workflow_mapping()
    workflow = json.loads((REPO_ROOT / "yue2_full.json").read_text())
    assert mapping["node_count"] == len(workflow["nodes"])
    assert mapping["workflow_id"] == workflow["id"]

    # Every mapped widget must actually exist in the graph with that value.
    widgets = {
        (node["type"], name): value
        for node in workflow["nodes"]
        for name, value in (node.get("widgets_values_named") or {}).items()
    }
    for entry in mapping["parameters"]:
        if entry["comfy_node_type"] and entry["comfy_widget"]:
            key = (entry["comfy_node_type"], entry["comfy_widget"])
            assert key in widgets
            assert widgets[key] == entry["workflow_value"]


def test_schema_disables_unsupported_options_with_a_reason(data_dir):
    capabilities = {
        "label": "test",
        "modes": ["full", "melody", "off"],
        "capabilities": {"cover": {"supported": False, "reason": "SheetSage2 missing"}},
    }
    described = describe_registry(capabilities)
    mode = next(p for p in described["parameters"] if p["key"] == "prompt.mode")
    cover = next(option for option in mode["options"] if option["value"] == "cover")
    assert cover["enabled"] is False
    assert cover["disabled_reason"] == "SheetSage2 missing"

    sampler = next(p for p in described["parameters"] if p["key"] == "synthesis.sampler_name")
    assert sampler["enabled"] is False
    assert "midpoint" in sampler["disabled_reason"]
