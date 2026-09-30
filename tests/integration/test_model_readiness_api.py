"""Inventory, selector and submission report the same readiness decision."""
from __future__ import annotations

import json

import pytest

from yue2_studio_core.model_metadata import GGUF_COMPANIONS
from yue2_studio_core.settings import get_settings


@pytest.fixture()
def downloaded_model(tmp_path, monkeypatch, data_dir):
    model = tmp_path / "models" / "gguf"
    model.mkdir(parents=True)
    filename = "yue2-3b-q4_0.gguf"
    for name in (filename, *GGUF_COMPANIONS):
        path = model / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"fixture")
        if name.endswith(".json"):
            path.write_text(json.dumps({"model_type": "yue2_vae" if "vae-config" in name else "yue2"}))
    (model / "studio-model.json").write_text(json.dumps({
        "filename": filename, "repo_id": "audio-cpp/Yue2-3B-GGUF", "revision": "a" * 40,
    }))
    cli = tmp_path / "audiocpp_cli"
    monkeypatch.setenv("YUE2_MODEL_PATH", str(model))
    monkeypatch.setenv("YUE2_MODELS_DIR", str(model.parent))
    monkeypatch.setenv("AUDIOCPP_CLI_PATH", str(cli))
    get_settings.cache_clear()
    return model, cli


def test_missing_runtime_is_consistent_across_api_and_schema(downloaded_model, api_client, sample_config, monkeypatch):
    from app.core.deps import capability_provider, system_info_provider

    model, _ = downloaded_model
    inventory = api_client.get("/api/v1/models").json()["items"]
    entry = next(item for item in inventory if item["id"] == str(model))
    assert entry["download_status"] == "downloaded"
    assert entry["files_complete"] is True
    assert entry["registration_status"] == "registered"
    assert entry["registry_id"] is not None
    assert entry["inference_status"] == "runtime_unavailable"
    schema = api_client.get("/api/v1/generation/schema").json()
    options = next(p for p in schema["parameters"] if p["key"] == "model.checkpoint")["options"]
    assert options[0]["value"] == "default"
    assert options[0]["enabled"] is False
    assert options[0]["disabled_reason"] == entry["problem"]
    for checkpoint in ("default", str(model)):
        response = api_client.post("/api/v1/generations", json={
            "config": {**sample_config, "model": {"checkpoint": checkpoint}},
        })
        assert response.status_code == 409
        assert response.json()["error_code"] == "UNSUPPORTED_CAPABILITY"
        assert response.json()["details"]["inference_status"] == "runtime_unavailable"
    assert api_client.get("/api/v1/generations").json()["total"] == 0
    monkeypatch.setattr(system_info_provider(), "worker_state", lambda: {"online": True})
    monkeypatch.setattr(capability_provider(), "runtime_probe", lambda: {
        "model_present": True, "vae_present": False,
    })
    assert api_client.get("/api/v1/health").json()["ready"] is False


def test_installing_runtime_enables_existing_files_and_preserves_request(downloaded_model, api_client, sample_config):
    model, cli = downloaded_model
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    response = api_client.post("/api/v1/generations", json={"config": sample_config})
    assert response.status_code == 201, response.text
    job = response.json()["generation"]
    assert job["config"]["model"]["checkpoint"] == "default"
    assert job["config"]["model"]["vae"] == "standard"
    entry = next(item for item in api_client.get("/api/v1/models").json()["items"] if item["id"] == str(model))
    assert entry["download_status"] == "downloaded"
    assert entry["inference_status"] == "ready"
    assert entry["validation_status"] == "not_validated"
    assert entry["currently_loaded"] is None


def test_inventory_registry_is_idempotent_and_runtime_remains_live(downloaded_model, api_client, data_dir):
    model, cli = downloaded_model
    first = next(item for item in api_client.get("/api/v1/models").json()["items"] if item["id"] == str(model))
    path = data_dir / "model-registry.json"
    snapshot, mtime = path.read_bytes(), path.stat().st_mtime_ns
    again = next(item for item in api_client.get("/api/v1/models").json()["items"] if item["id"] == str(model))
    assert first == again
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    refreshed = next(item for item in api_client.get("/api/v1/models").json()["items"] if item["id"] == str(model))
    assert refreshed["inference_ready"]
    assert refreshed["registry_id"] == first["registry_id"]
    assert path.read_bytes() == snapshot and path.stat().st_mtime_ns == mtime


def test_corrupt_registry_returns_actionable_error_without_overwriting(downloaded_model, api_client, data_dir):
    api_client.get("/api/v1/models")
    path = data_dir / "model-registry.json"
    backup = path.read_bytes()
    path.write_text("not json")
    response = api_client.get("/api/v1/models")
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_CONFIG"
    assert "left unchanged" in response.json()["error_message"]
    assert path.read_text() == "not json"
    path.write_bytes(backup)
    assert api_client.get("/api/v1/models").status_code == 200
