import asyncio

from yue2_studio_core.store import write_json_atomic


def model_id(client, path):
    return next(m["registry_id"] for m in client.get("/api/v1/models").json()["items"] if m["id"] == str(path))


def test_load_unload_commands_and_runtime_readback(runtime_worker, api_client):
    worker = runtime_worker
    registry_id = model_id(api_client, worker.settings.model_reference)
    vae_id = model_id(api_client, worker.settings.vae_reference)
    response = api_client.post(f"/api/v1/models/{registry_id}/load", json={"config": {"model": {"vae": vae_id, "checkpoint": "/ignored"}}})
    assert response.status_code == 202, response.text
    command = response.json()
    assert command["status"] == "queued" and command["worker_session"] == worker.session_id
    assert command["config"]["model"]["checkpoint"] == worker.settings.model_reference
    assert command["config"]["model"]["vae"] == worker.settings.vae_reference
    assert not worker.manager.loaded  # HTTP admission did not allocate anything
    assert api_client.post(f"/api/v1/models/{registry_id}/load", json={}).status_code == 409
    for entry_id in (registry_id, vae_id):
        assert not api_client.get(f"/api/v1/models/{entry_id}/deletion-preview").json()["can_delete"]
    claimed = worker.commands.claim(worker.worker_id, worker.session_id)
    asyncio.run(worker.run_command(claimed))
    ack = api_client.get(f"/api/v1/models/runtime-commands/{command['id']}").json()
    assert ack["status"] == "succeeded" and ack["result"]["loaded"] and ack["worker_online"]
    state = api_client.get("/api/v1/system/runtime").json()
    assert state["online"] and state["workers"][0]["model"]["lifecycle"] == "LOADED"
    response = api_client.post(f"/api/v1/models/{registry_id}/unload")
    assert response.status_code == 202 and worker.manager.loaded
    asyncio.run(worker.run_command(worker.commands.claim(worker.worker_id, worker.session_id)))
    assert api_client.get(f"/api/v1/models/runtime-commands/{response.json()['id']}").json()["result"]["lifecycle"] == "UNLOADED"


def test_offline_old_worker_and_vae_actions_are_rejected(runtime_worker, api_client):
    worker = runtime_worker
    registry_id = model_id(api_client, worker.settings.model_reference)
    vae_id = model_id(api_client, worker.settings.vae_reference)
    assert api_client.post(f"/api/v1/models/{vae_id}/load", json={}).status_code == 422
    assert api_client.post("/api/v1/models/missing/load", json={}).status_code == 404
    worker.write_heartbeat("stopped")
    assert api_client.post(f"/api/v1/models/{registry_id}/load", json={}).status_code == 409
    import json
    heartbeat = json.loads(worker.heartbeat_path.read_text())
    heartbeat.update(state="idle")
    heartbeat.pop("session_id")
    write_json_atomic(worker.heartbeat_path, heartbeat)
    assert api_client.post(f"/api/v1/models/{registry_id}/unload").status_code == 409


def test_failed_load_reports_error_and_keeps_api_usable(runtime_worker, api_client, monkeypatch):
    worker = runtime_worker
    from yue2_studio_core.errors import StudioError, ErrorCode
    def fail(*args):
        raise StudioError(ErrorCode.CUDA_OOM, "mock insufficient VRAM")
    monkeypatch.setattr(worker.manager, "_check_runtime", fail)
    registry_id = model_id(api_client, worker.settings.model_reference)
    response = api_client.post(f"/api/v1/models/{registry_id}/load")
    assert response.status_code == 202
    asyncio.run(worker.run_command(worker.commands.claim(worker.worker_id, worker.session_id)))
    ack = api_client.get(f"/api/v1/models/runtime-commands/{response.json()['id']}").json()
    assert ack["status"] == "failed" and ack["error"]["error_code"] == "CUDA_OOM"
    assert not ack["result"]["loaded"] and api_client.get("/api/v1/system/runtime").status_code == 200


def test_gguf_and_vllm_preload_are_explicitly_unsupported(runtime_worker, api_client, download_package):
    import shutil
    worker = runtime_worker
    gguf = worker.settings.models_path / "gguf"
    shutil.copytree(download_package.source, gguf)
    write_json_atomic(gguf / "studio-model.json", {"filename": "custom.gguf"})
    gguf_id = model_id(api_client, gguf)
    response = api_client.post(f"/api/v1/models/{gguf_id}/load", json={})
    assert response.status_code == 409 and "per generation" in response.json()["error_message"]
    registry_id = model_id(api_client, worker.settings.model_reference)
    response = api_client.post(f"/api/v1/models/{registry_id}/load", json={"config": {"model": {"compute_backend": "vllm"}}})
    assert response.status_code == 409 and "no preload" in response.json()["error_message"]
    assert not worker.commands.list()
