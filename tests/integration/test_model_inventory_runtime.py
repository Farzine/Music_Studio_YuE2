"""Installed-model UI facts come from worker snapshots, never download state."""
import json

from yue2_studio_core.store import write_json_atomic


def inventory(client, worker, role="model"):
    path = worker.settings.model_reference if role == "model" else worker.settings.vae_reference
    return next(m for m in client.get("/api/v1/models").json()["items"] if m["id"] == path)


def publish(worker, **snapshot):
    heartbeat = json.loads(worker.heartbeat_path.read_text())
    heartbeat["model"].update(snapshot)
    write_json_atomic(worker.heartbeat_path, heartbeat)


def test_inventory_separates_readiness_residency_and_action_availability(runtime_worker, api_client):
    worker = runtime_worker
    entry = inventory(api_client, worker)
    assert entry["download_status"] == "downloaded" and entry["inference_ready"]
    assert entry["currently_loaded"] is False
    assert entry["runtime_actions"]["load"]["allowed"]
    vae = inventory(api_client, worker, "vae")
    assert not vae["runtime_actions"]["load"]["allowed"]
    assert "VAE" in vae["runtime_actions"]["unload"]["reason"]

    queued = api_client.post(f'/api/v1/models/{entry["registry_id"]}/load').json()
    assert queued["status"] == "queued"
    assert inventory(api_client, worker)["currently_loaded"] is False
    publish(worker, model=worker.settings.model_reference, vae=worker.settings.vae_reference,
            lifecycle="LOADED", loaded=True, residency_known=True,
            model_device="cuda:0", model_gpu_resident=True, vae_device=None, vae_gpu_resident=False)
    entry = inventory(api_client, worker)
    assert entry["currently_loaded"] is True
    assert entry["runtime"][0]["model_device"] == "cuda:0"
    assert inventory(api_client, worker, "vae")["currently_loaded"] is False

    publish(worker, residency_known=False, lifecycle="UNLOAD_FAILED")
    assert inventory(api_client, worker)["currently_loaded"] is None
    worker.write_heartbeat("stopped")
    entry = inventory(api_client, worker)
    assert entry["currently_loaded"] is None
    assert not entry["runtime_actions"]["load"]["allowed"]


def test_unknown_child_and_cpu_placements_are_not_claimed_as_gpu_residency(runtime_worker, api_client):
    worker = runtime_worker
    publish(worker, model=worker.settings.model_reference, loaded=True, residency_known=False,
            lifecycle="IN_USE", residency_mode="per_job", model_device=None, model_gpu_resident=None)
    assert inventory(api_client, worker)["currently_loaded"] is None
    publish(worker, model_device="cpu", model_gpu_resident=False, residency_known=True)
    entry = inventory(api_client, worker)
    assert entry["currently_loaded"] is True
    assert entry["runtime"][0]["model_gpu_resident"] is False
    publish(worker, model_device=None, model_gpu_resident=None)
    assert inventory(api_client, worker)["currently_loaded"] is None


def test_gguf_inventory_explains_persistent_load_limit(runtime_worker, api_client, download_package):
    import shutil
    worker = runtime_worker
    model = worker.settings.models_path / "gguf"
    shutil.copytree(download_package.source, model)
    write_json_atomic(model / "studio-model.json", {"filename": "custom.gguf"})
    entry = next(m for m in api_client.get("/api/v1/models").json()["items"] if m["id"] == str(model))
    assert not entry["runtime_actions"]["load"]["allowed"]
    assert "per generation" in entry["runtime_actions"]["load"]["reason"]
    response = api_client.post(f'/api/v1/models/{entry["registry_id"]}/load')
    assert response.status_code == 409
