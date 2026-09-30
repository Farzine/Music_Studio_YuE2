"""Model actions agree with inventory and admission, using tiny real files."""
import json

import pytest

from yue2_studio_core.settings import get_settings


@pytest.fixture()
def model_paths(tmp_path, data_dir, monkeypatch, native_model_files):
    root = tmp_path / "models"
    model = native_model_files(root / "native")
    vae = native_model_files(root / "vae", role="vae")
    monkeypatch.setenv("YUE2_MODELS_DIR", str(root))
    monkeypatch.setenv("YUE2_MODEL_PATH", str(model))
    monkeypatch.setenv("YUE2_VAE_PATH", str(vae))
    monkeypatch.setenv("YUE2_VAE_LEGACY_PATH", str(root / "missing-legacy"))
    get_settings.cache_clear()
    return model, vae


def installed_id(client, path):
    return next(item["registry_id"] for item in client.get("/api/v1/models").json()["items"] if item["id"] == str(path))


def deletion(client, registry_id, preview):
    return client.request("DELETE", f"/api/v1/models/{registry_id}", json={
        "confirmation_token": preview["confirmation_token"], "confirmed_path": preview["path"],
    })


def test_inspect_validate_and_confirm_delete(model_paths, api_client):
    model, vae = model_paths
    registry_id = installed_id(api_client, model)
    inspected = api_client.get(f"/api/v1/models/{registry_id}")
    assert inspected.status_code == 200
    assert inspected.json()["model"]["id"] == str(model)
    assert inspected.json()["validation"] is None
    result = api_client.post(f"/api/v1/models/{registry_id}/validate", json={})
    assert result.status_code == 200
    assert result.json()["validation"]["validation_status"] == "validated"
    assert api_client.get(f"/api/v1/models/{registry_id}").json()["model"]["validation_status"] == "validated"
    assert api_client.request("DELETE", f"/api/v1/models/{registry_id}", json={}).status_code == 422
    preview = api_client.get(f"/api/v1/models/{registry_id}/deletion-preview").json()
    assert preview["can_delete"] and preview["warning"]
    assert deletion(api_client, registry_id, preview).json()["complete"]
    assert not model.exists() and vae.is_dir()
    assert api_client.get(f"/api/v1/models/{registry_id}").status_code == 404


def test_queued_generation_protects_model_and_selected_vae(model_paths, api_client, sample_config):
    model, vae = model_paths
    ids = [installed_id(api_client, path) for path in (model, vae)]
    response = api_client.post("/api/v1/generations", json={"config": sample_config})
    assert response.status_code == 201, response.text
    generation = response.json()["generation"]
    assert generation["config"]["model"]["checkpoint"] == "default"
    assert generation["config"]["model"]["vae"] == "standard"
    for registry_id in ids:
        preview = api_client.get(f"/api/v1/models/{registry_id}/deletion-preview").json()
        assert not preview["can_delete"]
        assert deletion(api_client, registry_id, preview).status_code == 409
    assert api_client.post(f"/api/v1/generations/{generation['id']}/cancel").status_code == 200
    for registry_id in ids:
        preview = api_client.get(f"/api/v1/models/{registry_id}/deletion-preview").json()
        assert deletion(api_client, registry_id, preview).json()["complete"]


def test_failed_validation_blocks_task_submission(model_paths, api_client, sample_config):
    model, _ = model_paths
    registry_id = installed_id(api_client, model)
    (model / "model.safetensors").write_bytes(b"corrupt")
    response = api_client.post(f"/api/v1/models/{registry_id}/validate", json={})
    assert response.status_code == 200 and response.json()["validation"]["validation_status"] == "failed"
    response = api_client.post("/api/v1/generations", json={"config": sample_config})
    assert response.status_code == 422, response.text
    assert response.json()["details"]["inference_status"] == "validation_failed"
    assert api_client.get("/api/v1/generations").json()["total"] == 0


def test_incompatible_native_vae_has_actionable_error(model_paths, api_client, sample_config):
    _, vae = model_paths
    config = json.loads((vae / "config.json").read_text())
    config["latent_dim"] = 128
    (vae / "config.json").write_text(json.dumps(config))
    response = api_client.post("/api/v1/generations", json={"config": sample_config})
    assert response.status_code == 409, response.text
    assert response.json()["details"]["parameter"] == "model.vae"
    assert "latent width" in response.json()["error_message"]


def test_changed_preview_and_unknown_ids_are_rejected(model_paths, api_client):
    model, _ = model_paths
    registry_id = installed_id(api_client, model)
    preview = api_client.get(f"/api/v1/models/{registry_id}/deletion-preview").json()
    (model / "file.part").write_bytes(b"new partial file")
    assert deletion(api_client, registry_id, preview).status_code == 409
    assert model.exists()
    assert api_client.get("/api/v1/models/not-a-registry-id").status_code == 404
