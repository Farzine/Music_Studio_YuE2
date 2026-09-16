"""Every parameter must be explainable to someone who is not an ML engineer."""
from __future__ import annotations

import pytest

from yue2_studio_core.parameters import load_registry

BANNED_PHRASINGS = (
    "controls the sampling temperature",
    "sets the top_p",
    "see documentation",
    "tbd",
)


@pytest.fixture()
def parameters(data_dir):
    return load_registry()["parameters"]


def test_every_parameter_has_guidance(parameters):
    missing = [p["key"] for p in parameters if not p.get("guidance")]
    assert missing == [], f"parameters with no help: {missing}"


def test_guidance_explains_rather_than_restates(parameters):
    for parameter in parameters:
        guidance = parameter["guidance"]
        what = guidance["what"]
        assert len(what) > 60, f"{parameter['key']}: 'what' is too short to be useful"
        assert what.rstrip().endswith("."), f"{parameter['key']}: 'what' should read as prose"
        lowered = what.lower()
        for phrase in BANNED_PHRASINGS:
            assert phrase not in lowered, f"{parameter['key']}: restates the parameter name"
        # A label repeated verbatim as the whole explanation is not an explanation.
        assert lowered.strip(" .") != parameter["label"].lower()


def test_severity_is_used_semantically(parameters):
    by_key = {p["key"]: p["guidance"]["severity"] for p in parameters}

    # Things that genuinely destabilise output, cost VRAM, or cost time.
    for key in (
        "sampling.max_duration_seconds",
        "sampling.temperature",
        "sampling.repetition_penalty",
        "decoder.mode",
        "decoder.tile_frames",
        "model.memory_budget_gib",
        "model.quantization",
        "synthesis.ode_steps",
    ):
        assert by_key[key] == "caution", f"{key} should carry a caution icon"

    # Harmless controls must not shout.
    for key in (
        "sampling.top_p",
        "sampling.top_k",
        "sampling.seed",
        "output.filename_prefix",
        "model.revision",
        "decoder.halo_frames",
    ):
        assert by_key[key] == "info", f"{key} should not carry a warning icon"


def test_numeric_parameters_say_which_way_is_which(parameters):
    for parameter in parameters:
        if parameter["type"] not in {"float", "int"}:
            continue
        if not parameter["native"]["supported"]:
            continue  # ComfyUI-only entries explain that instead
        guidance = parameter["guidance"]
        assert guidance.get("more") or guidance.get("recommended"), parameter["key"]
        assert guidance.get("recommended"), f"{parameter['key']} needs a recommended value"


def test_unsupported_parameters_say_what_to_use_instead(parameters):
    for parameter in parameters:
        if parameter["native"]["supported"]:
            continue
        guidance = parameter["guidance"]
        assert "not applicable" in (guidance.get("recommended", "").lower()), parameter["key"]
        assert guidance.get("cost", "").lower().startswith("not applied"), parameter["key"]
