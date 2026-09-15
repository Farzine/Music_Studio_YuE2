"""Parameter registry: one definition per configurable value.

The registry is the only place a parameter is described. The API serves it, the
frontend renders forms from it, the worker checks a request against it, and the
ComfyUI mapping file is generated from it. Nothing duplicates these definitions.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import UnsupportedCapabilityError, ValidationError
from .models import GenerationConfig, Preset
from .settings import get_settings


def _read(name: str) -> dict:
    path = get_settings().configs_path / name
    if not path.is_file():
        raise FileNotFoundError(f"missing configuration file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_registry() -> dict:
    return _read("parameter-registry.json")


@lru_cache(maxsize=1)
def load_defaults_document() -> dict:
    return _read("yue2.defaults.json")


@lru_cache(maxsize=1)
def load_capabilities_document() -> dict:
    return _read("yue2.capabilities.json")


@lru_cache(maxsize=1)
def load_presets_document() -> dict:
    return _read("presets.json")


@lru_cache(maxsize=1)
def load_workflow_mapping() -> dict:
    return _read("workflow-mapping.json")


def default_config() -> GenerationConfig:
    return GenerationConfig.model_validate(load_defaults_document()["config"])


def deep_merge(base: dict, overrides: dict) -> dict:
    """Recursive dict merge; ``overrides`` wins, including explicit nulls."""
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def config_from_overrides(overrides: dict | None) -> GenerationConfig:
    """Build a full config by merging a partial request over the defaults."""
    merged = deep_merge(load_defaults_document()["config"], overrides or {})
    try:
        return GenerationConfig.model_validate(merged)
    except Exception as exc:  # pydantic ValidationError and friends
        raise ValidationError(str(exc)) from exc


def builtin_presets() -> list[Preset]:
    document = load_presets_document()
    presets = []
    for entry in document["presets"]:
        presets.append(
            Preset(
                id=entry["id"],
                name=entry["name"],
                description=entry.get("description", ""),
                builtin=True,
                config=config_from_overrides(entry.get("overrides")),
            )
        )
    return presets


def get_path(config: GenerationConfig, dotted: str) -> Any:
    value: Any = config
    for part in dotted.split("."):
        value = getattr(value, part)
    return value


def parameter_index() -> dict[str, dict]:
    return {parameter["key"]: parameter for parameter in load_registry()["parameters"]}


def unsupported_parameters_in_use(config: GenerationConfig, backend: str) -> list[dict]:
    """Parameters the user set that the active backend cannot honour.

    Returning them rather than dropping them is the point: the caller either
    refuses the request or shows the reason. Values equal to the registry
    default are not "in use".
    """
    violations: list[dict] = []
    for parameter in load_registry()["parameters"]:
        native = parameter["native"]
        if backend in {"native", "mock"} and not native["supported"]:
            value = get_path(config, parameter["key"])
            if value is not None and value != parameter.get("default"):
                violations.append(
                    {
                        "parameter": parameter["key"],
                        "label": parameter["label"],
                        "value": value,
                        "reason": native.get("note") or "No equivalent in the native runtime.",
                        "comfy_node": parameter["comfy"].get("node"),
                    }
                )
    return violations


def backend_capabilities(backend: str) -> dict:
    document = load_capabilities_document()
    if backend not in document["backends"]:
        raise ValidationError(f"unknown backend '{backend}'")
    return copy.deepcopy(document["backends"][backend])


def assert_capability(capabilities: dict, name: str) -> None:
    entry = capabilities.get("capabilities", {}).get(name)
    if not entry or not entry.get("supported"):
        reason = (entry or {}).get("reason", "Not available in this installation.")
        raise UnsupportedCapabilityError(f"{name} is not available: {reason}", details={"capability": name})


def describe_registry(capabilities: dict, dynamic_options: dict[str, list[dict]] | None = None) -> dict:
    """Registry annotated for the active backend.

    Each parameter gains ``enabled`` and, when disabled, ``disabled_reason``,
    so the frontend never has to decide on its own what a backend supports.
    """
    registry = copy.deepcopy(load_registry())
    supported_modes = set(capabilities.get("modes", []))
    capability_map = capabilities.get("capabilities", {})
    dynamic_options = dynamic_options or {}

    for parameter in registry["parameters"]:
        native = parameter["native"]
        parameter["enabled"] = bool(native["supported"])
        if not native["supported"]:
            parameter["disabled_reason"] = native.get("note") or "Not supported by the active backend."
        if parameter.get("readonly"):
            parameter["enabled"] = False
            parameter.setdefault("disabled_reason", "Fixed by the runtime.")

        source = parameter.get("dynamic_options")
        if source:
            parameter["options"] = dynamic_options.get(source, [])

        for option in parameter.get("options") or []:
            capability = option.get("capability")
            mode_supported = parameter["key"] != "prompt.mode" or option["value"] in supported_modes
            if capability:
                entry = capability_map.get(capability, {})
                option["enabled"] = bool(entry.get("supported")) and mode_supported
                if not option["enabled"]:
                    option["disabled_reason"] = entry.get("reason") or "Not available in this installation."
            else:
                option["enabled"] = mode_supported
                if not mode_supported:
                    option["disabled_reason"] = "The active backend does not offer this mode."

    registry["backend"] = capabilities.get("label")
    registry["capabilities"] = capability_map
    return registry
