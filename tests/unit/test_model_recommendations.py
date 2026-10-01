"""Deterministic model capacity/compatibility estimates without CUDA or network."""
from pathlib import Path
import json

import pytest
from pydantic import ValidationError

from yue2_studio_core.model_metadata import ModelMetadata
from yue2_studio_core.model_recommendations import GIB, assess_model, gpu_capacity, model_memory, sort_recommendations
from yue2_studio_core.settings import Settings


@pytest.fixture()
def scenario(tmp_path):
    def entry(name, role="model", **changes):
        path = tmp_path / name
        path.mkdir()
        config = {"model_type": "yue2" if role == "model" else "yue2_vae", "latent_dim": 64}
        if role == "model":
            config.update(num_hidden_layers=28, num_key_value_heads=8, head_dim=128, max_position_embeddings=1024)
        (path / "config.json").write_text(json.dumps(config))
        values = dict(id=str(path), path=str(path), label=name, role=role, is_local=True,
                      format="safetensors", filename="model.safetensors", bytes=GIB,
                      backend="native", architecture=config["model_type"], precision="F16",
                      download_status="downloaded", files_complete=True, compatibility_status="supported",
                      inference_status="ready", validation_status="validated", registration_status="registered")
        values.update(changes)
        return ModelMetadata(**values)
    return dict(model=entry("model"), vae=entry("vae", "vae"),
                settings=Settings(_env_file=None),
                device=dict(index=0, name="test GPU", cuda_available=True, selectable=True,
                            memory_total_bytes=24*GIB, memory_free_bytes=20*GIB,
                            bf16_supported=True, utilisation_percent=0),
                runtime=dict(backend="native", native_available=True, audiocpp_available=True),
                ram=dict(available_bytes=64*GIB))


def assess(scenario, **changes):
    arguments = {**scenario, **changes}
    model = arguments.pop("model")
    arguments["capacity"] = gpu_capacity(arguments["device"], arguments["settings"])
    return assess_model(model, **arguments)


def test_vram_is_runtime_weights_plus_vae_cache_workspace(scenario):
    result = assess(scenario)
    memory = result["estimate"]
    assert memory["weight_runtime_bytes"] == int(1.25*GIB)
    assert memory["vae_bytes"] == 2*GIB  # F16 storage, native FP32 decoder
    assert memory["kv_cache_bytes"] == 28*2*8*128*2*1024*2
    assert memory["estimated_peak_bytes"] == sum(memory[k] for k in (
        "weight_runtime_bytes", "vae_bytes", "kv_cache_bytes", "runtime_overhead_bytes"))
    assert memory["estimated_peak_bytes"] > result["model_bytes"]
    assert result["status"] == "recommended"
    assert result["parameters"] is None  # Never infer a count from file size/name.
    assert result["runnable"]


def test_parameter_metadata_increases_native_bf16_weight_lower_bound(scenario):
    model = scenario["model"].model_copy(update={"parameter_count": 3_000_000_000})
    assert assess(scenario, model=model)["estimate"]["weights_bytes"] == 6_000_000_000
    assert assess(scenario, model=model)["parameters"] == 3_000_000_000


def test_remote_native_config_still_checks_selected_vae_latent_width(scenario):
    model = scenario["model"].model_copy(update={"path": None, "is_local": False,
                                              "validation_status": "not_validated", "inference_status": "files_missing"})
    result = assess(scenario, model=model, model_config={"model_type": "yue2", "latent_dim": 32})
    assert result["status"] == "cannot_run" and not result["runnable"]
    assert any("latent width" in reason for reason in result["reasons"])


def test_capacity_reserves_and_hypothetical_parameters(scenario):
    result = gpu_capacity(scenario["device"], scenario["settings"])
    assert result["safety_margin_bytes"] >= 24*GIB*0.2
    assert result["usable_bytes"] == 20*GIB-result["safety_margin_bytes"]
    assert 0 < result["conservative_model_bytes"] < result["comfortable_model_bytes"] < result["upper_model_bytes"]
    assert result["basis"] == "heuristic"
    assert result["quantizations"][0]["approximate_parameters"] > result["quantizations"][-1]["approximate_parameters"]
    changed = scenario["settings"].model_copy(update={"model_vram_safety_fraction": 0.5})
    assert gpu_capacity(scenario["device"], changed)["comfortable_model_bytes"] < result["comfortable_model_bytes"]


@pytest.mark.parametrize("changes", [
    {"memory_free_bytes": None}, {"memory_free_bytes": -1}, {"memory_total_bytes": None},
    {"memory_free_bytes": 100*GIB}, {"cuda_available": None}, {"selectable": False},
])
def test_unknown_or_invalid_gpu_facts_never_produce_capacity(scenario, changes):
    device = {**scenario["device"], **changes}
    assert gpu_capacity(device, scenario["settings"])["comfortable_model_bytes"] is None
    result = assess(scenario, device=device)
    assert result["status"] == "unknown"
    assert not result["runnable"]


def test_safety_boundary_distinguishes_margin_from_physical_failure(scenario):
    peak = assess(scenario)["peak_bytes"]
    settings = scenario["settings"].model_copy(update={"model_vram_safety_fraction": 0, "model_vram_safety_gib": 1})
    device = {**scenario["device"], "memory_free_bytes": peak+GIB}
    assert assess(scenario, settings=settings, device=device)["status"] == "supported"
    device["memory_free_bytes"] -= 1
    result = assess(scenario, settings=settings, device=device)
    assert result["status"] == "not_recommended" and result["excess_bytes"] == 1
    device["memory_free_bytes"] = peak-1
    assert assess(scenario, settings=settings, device=device)["status"] == "cannot_run"


def test_idle_residency_is_conditional_and_busy_memory_is_not_reclaimed(scenario):
    device = {**scenario["device"], "loaded_model": scenario["model"].id,
              "loaded_vae": scenario["vae"].id, "reserved_bytes": 10*GIB}
    capacity = gpu_capacity(device, scenario["settings"])
    assert capacity["reclaimable_bytes"] == 4*GIB  # Never more than physical used memory.
    assert assess(scenario, device=device)["status"] == "ready"
    assert any("unloading" in reason for reason in assess(scenario, device=device)["reasons"])
    device["worker_busy"] = True
    assert gpu_capacity(device, scenario["settings"])["reclaimable_bytes"] == 0
    assert assess(scenario, device=device)["status"] == "unknown"
    device["loaded_model"] = None
    assert gpu_capacity(device, scenario["settings"])["reclaimable_bytes"] == 0


def test_changing_vae_is_not_mistaken_for_already_loaded_configuration(scenario):
    device = {**scenario["device"], "loaded_model": scenario["model"].id, "loaded_vae": "different"}
    result = assess(scenario, device=device)
    assert result["currently_loaded"]
    assert result["status"] == "recommended"  # requires different decoder load


@pytest.mark.parametrize("changes, status", [
    ({"validation_status": "not_validated"}, "possibly_supported"),
    ({"validation_status": "failed"}, "cannot_run"),
    ({"compatibility_status": "incompatible"}, "cannot_run"),
    ({"architecture": None}, "unknown"),
    ({"bytes": None}, "unknown"),
    ({"files_complete": False}, "cannot_run"),
    ({"deletion_status": "deleting"}, "cannot_run"),
    ({"format": "unknown", "backend": None}, "cannot_run"),
])
def test_compatibility_and_validation_are_not_file_size_fits(scenario, changes, status):
    model = scenario["model"].model_copy(update=changes)
    result = assess(scenario, model=model)
    assert result["status"] == status
    assert not result["runnable"]
    assert result["reasons"]


def test_native_precision_and_runtime_requirements(scenario):
    assert assess(scenario, device={**scenario["device"], "bf16_supported": False})["status"] == "cannot_run"
    assert assess(scenario, device={**scenario["device"], "bf16_supported": None})["status"] == "unknown"
    assert assess(scenario, runtime={**scenario["runtime"], "native_available": False})["status"] == "unknown"
    assert assess(scenario, runtime={**scenario["runtime"], "backend": "mock"})["status"] == "cannot_run"
    assert assess(scenario, compute_backend="vllm")["status"] == "unknown"


def test_ram_pressure_and_utilisation_affect_recommendations(scenario):
    assert assess(scenario, ram={"available_bytes": GIB})["status"] == "not_recommended"
    assert assess(scenario, ram={"available_bytes": None})["status"] == "possibly_supported"
    assert assess(scenario, device={**scenario["device"], "utilisation_percent": 90})["status"] == "not_recommended"


def test_vae_choice_is_required_and_mismatch_is_explicit(scenario):
    assert assess(scenario, vae=None)["status"] == "unknown"
    config = Path(scenario["vae"].path)/"config.json"
    config.write_text('{"model_type":"yue2_vae","latent_dim":32}')
    result = assess(scenario)
    assert result["status"] == "cannot_run"
    assert any("latent width" in reason for reason in result["reasons"])
    invalid = scenario["vae"].model_copy(update={"validation_status": "failed", "inference_status": "validation_failed"})
    assert assess(scenario, vae=invalid)["status"] == "cannot_run"


def test_offload_does_not_pretend_full_load_is_cheaper(scenario):
    regular, offload = assess(scenario), assess(scenario, offload_ar=True)
    assert regular["peak_bytes"] == offload["peak_bytes"]
    assert offload["offload_supported"]
    assert any("full model load" in reason for reason in offload["reasons"])


def test_unknown_cache_uses_disclosed_fallback(scenario):
    (Path(scenario["model"].path)/"config.json").write_text('{"model_type":"yue2"}')
    result = assess(scenario)
    assert result["estimate"]["kv_source"] == "configured_fallback"
    assert result["estimate"]["kv_cache_bytes"] == 2*GIB


def test_gguf_uses_bundled_vae_and_refuses_missing_cli_or_offload(scenario):
    model = scenario["model"].model_copy(update={"format": "gguf", "backend": "audiocpp", "quantization": "Q4_0"})
    (Path(model.path)/"yue2-vae-f16.gguf").write_bytes(b"header")
    result = assess(scenario, model=model, vae=None)
    assert result["status"] == "recommended"
    assert result["estimate"]["vae_bytes"] == 6
    assert result["vae_id"] is None
    assert not result["offload_supported"]
    assert assess(scenario, model=model, offload_ar=True)["status"] == "cannot_run"
    assert assess(scenario, model=model, runtime={**scenario["runtime"], "audiocpp_available": False})["status"] == "cannot_run"


def test_native_allocator_budget_applies_even_on_large_gpu(scenario):
    model = scenario["model"].model_copy(update={"bytes": 30*GIB})
    device = {**scenario["device"], "memory_total_bytes": 80*GIB, "memory_free_bytes": 70*GIB}
    limited = assess(scenario, model=model, device=device, memory_budget_gib=40)
    assert limited["safe_budget_bytes"] == 38*GIB
    assert limited["status"] == "not_recommended"
    assert assess(scenario, model=model, device=device, memory_budget_gib=80)["status"] == "recommended"


def test_ranking_is_stable_without_inventing_parameter_counts(scenario):
    first = assess(scenario)
    second = {**first, "id": "another", "parameters": None}
    assert sort_recommendations([first, second]) == sort_recommendations([second, first])
    assert all(item["parameters"] is None for item in sort_recommendations([second, first]))


def test_remote_candidate_and_unbounded_metadata_are_not_runnable(scenario):
    model = scenario["model"].model_copy(update={"is_local": False, "path": None, "files_complete": False,
                                                "inference_status": "files_missing", "validation_status": "not_validated"})
    result = assess(scenario, model=model)
    assert result["status"] == "possibly_supported"
    assert not result["runnable"]
    assert any("not installed" in reason for reason in result["reasons"])
    invalid = scenario["model"].model_copy(update={"parameter_count": 10**300})
    assert assess(scenario, model=invalid)["status"] == "unknown"
    config = Path(scenario["model"].path)/"config.json"
    config.write_text(json.dumps({"model_type": "yue2", "num_hidden_layers": 10**300}))
    assert assess(scenario)["status"] == "unknown"


@pytest.mark.parametrize("field,value", [("model_vram_safety_fraction", 1), ("model_vram_safety_gib", -1),
                                          ("model_weight_overhead_factor", 0.9), ("model_unknown_kv_gib", float("nan")),
                                          ("model_runtime_overhead_gib", 1e300)])
def test_invalid_reserve_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
