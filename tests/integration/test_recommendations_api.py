"""Recommendations use installed metadata and worker-selected GPUs, without CUDA."""
from datetime import datetime, timezone
import json

import pytest

from app.core.deps import store_provider
from app.services import system_info
from yue2_studio_core.settings import get_settings


@pytest.fixture()
def model_paths(tmp_path, data_dir, monkeypatch, native_model_files):
    root = tmp_path/"models"
    model = native_model_files(root/"model")
    vae = native_model_files(root/"vae", role="vae")
    config = json.loads((model/"config.json").read_text())
    config.update(num_hidden_layers=2, num_key_value_heads=2, head_dim=8, max_position_embeddings=128)
    (model/"config.json").write_text(json.dumps(config))
    for key, value in {"YUE2_MODELS_DIR": root, "YUE2_MODEL_PATH": model, "YUE2_VAE_PATH": vae,
                       "YUE2_VAE_LEGACY_PATH": root/"missing", "YUE2_BACKEND": "native"}.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setattr(system_info, "_gpus", lambda: ([], None, None))
    monkeypatch.setattr(system_info, "system_memory", lambda: dict(
        available_bytes=64*2**30, total_bytes=128*2**30, used_bytes=64*2**30,
        cpu_name="test", logical_cpu_count=8, source="mock"))
    get_settings.cache_clear()
    return model, vae


def worker(*, stopped=False, busy=False):
    store = store_provider()
    store.write_runtime_settings({"device_index": 1})
    directory = store.root/"worker"
    directory.mkdir(exist_ok=True)
    payload = dict(state="stopped" if stopped else "busy" if busy else "idle", backend="native",
                   updated_at=datetime.now(timezone.utc).isoformat(),
                   runtime={"cuda": "12.6", "torch": "2.10", "yue2-infer": "0.1.6"},
                   gpu=dict(available=True, active_index=1, cuda_visible_devices="1,0", devices=[
                       dict(index=0, uuid="GPU-1", name="small", total_bytes=4*2**30, free_bytes=2*2**30,
                            bf16_supported=True, compute_capability="8.9"),
                       dict(index=1, uuid="GPU-0", name="large", total_bytes=24*2**30, free_bytes=20*2**30,
                            bf16_supported=True, compute_capability="8.9")]))
    (directory/"test.json").write_text(json.dumps(payload))


def validate_models(client):
    for model in client.get("/api/v1/models").json()["items"]:
        if model["is_local"]:
            response = client.post(f"/api/v1/models/{model['registry_id']}/validate", json={})
            assert response.status_code == 200
            assert response.json()["validation"]["validation_status"] == "validated"


def test_recommendations_use_selected_gpu_and_real_registry_metadata(model_paths, api_client):
    model, vae = model_paths
    worker()
    validate_models(api_client)
    response = api_client.get("/api/v1/system/model-recommendation")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["device_index"] == 1
    assert len(body["capacities"]) == 2
    selected = next(item for item in body["items"] if item["id"] == str(model))
    assert selected["status"] == "recommended" and selected["runnable"]
    assert selected["parameters"] is None
    assert selected["vae_id"] == str(vae)
    assert selected["estimate"]["kv_source"] == "model_config_full_context_two_cfg_branches"
    small = api_client.get("/api/v1/system/model-recommendation?device_index=0").json()
    assert small["items"][0]["status"] == "cannot_run"
    assert small["items"][0]["excess_bytes"] > 0
    assert body["variants"] == body["items"]  # preserve legacy projection shape
    assert body["max_parameters"] is None
    assert api_client.get("/api/v1/system/model-recommendation?device_index=31").status_code == 422
    assert api_client.get("/api/v1/system/model-recommendation?compute_backend=invalid").status_code == 422
    assert api_client.get("/api/v1/system/model-recommendation?budget_gib=1").status_code == 422
    assert api_client.get("/api/v1/system/vram-estimate?seconds=60&budget_gib=inf").status_code == 422


def test_unvalidated_and_unknown_vae_never_become_runnable(model_paths, api_client):
    worker()
    body = api_client.get("/api/v1/system/model-recommendation").json()
    assert body["items"][0]["status"] == "possibly_supported"
    assert body["recommended"] is None
    validate_models(api_client)
    body = api_client.get("/api/v1/system/model-recommendation?vae=not-installed").json()
    assert body["items"][0]["status"] == "unknown"
    assert not body["items"][0]["runnable"]


def test_offline_worker_has_no_runnable_recommendations(model_paths, api_client):
    validate_models(api_client)
    worker(stopped=True)
    body = api_client.get("/api/v1/system/model-recommendation").json()
    assert body["capacities"] == []
    assert body["recommended"] is None and body["max_model_bytes"] is None


def test_task_warning_uses_actual_chosen_model_and_shared_estimate(model_paths, api_client):
    model, _ = model_paths
    worker()
    validate_models(api_client)
    store_provider().write_runtime_settings({"device_index": 0})
    body = api_client.get("/api/v1/system/model-recommendation").json()
    params = dict(seconds=600, decoder_mode="tiled", budget_gib=40, model=str(model))
    warning = api_client.get("/api/v1/system/vram-estimate", params=params).json()["warning"]
    assert warning["estimate_gib"] == round(body["items"][0]["peak_bytes"]/2**30, 1)
    assert "GPU 0" in warning["message"]
    params["model"] = "not-installed"
    assert api_client.get("/api/v1/system/vram-estimate", params=params).json()["warning"] is None
    store_provider().write_runtime_settings({"device_index": 1})
    params.update(model=str(model), decoder_mode="full")
    warning = api_client.get("/api/v1/system/vram-estimate", params=params).json()["warning"]
    assert "unprofiled" in warning["message"]
