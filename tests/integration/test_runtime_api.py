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


def switch_devices(worker, monkeypatch):
    from services.yue2_worker import worker as module
    from app.services import system_info
    monkeypatch.setattr(system_info, "_gpus", lambda: ([], None, None))
    monkeypatch.setattr(module, "gpu_snapshot", lambda index=None: {
        "available": True, "active_index": index,
        "devices": [{"index": i, "name": f"Mock GPU {i}", "total_bytes": 24 * 2**30,
                     "free_bytes": 20 * 2**30} for i in (0, 1)]})
    worker.write_heartbeat("idle")


def test_device_switch_queues_then_commits_and_exposes_ack(runtime_worker, api_client, monkeypatch):
    worker = runtime_worker
    from yue2_studio_core.models import GenerationConfig
    worker.manager.acquire(GenerationConfig())
    switch_devices(worker, monkeypatch)
    registry_id = model_id(api_client, worker.settings.model_reference)
    vae_id = model_id(api_client, worker.settings.vae_reference)
    response = api_client.put("/api/v1/system/device", json={"device_index": 1})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["selected_index"] == 0 and body["active_index"] == 0
    command = body["switch_command"]
    assert command["status"] == "queued" and command["device_index"] == 1
    assert worker.store.device_index() == 0 and worker.manager.state()["device_index"] == 0
    assert api_client.put("/api/v1/system/device", json={"device_index": 0}).status_code == 409
    assert api_client.post(f"/api/v1/models/{registry_id}/load").status_code == 409
    # Pending command protects rollback inputs even if the idle model is released.
    worker.manager.release()
    for entry in (registry_id, vae_id):
        assert not api_client.get(f"/api/v1/models/{entry}/deletion-preview").json()["can_delete"]
    worker.manager.acquire(GenerationConfig())
    asyncio.run(worker.run_command(worker.commands.claim(worker.worker_id, worker.session_id)))
    result = api_client.get("/api/v1/system/gpus").json()
    assert result["selected_index"] == result["active_index"] == 1
    assert result["switch_command"]["status"] == "succeeded"
    assert result["switch_command"]["progress"]["stage"] == "ready"
    assert not result["pending_restart"]
    assert api_client.get(f"/api/v1/models/runtime-commands/{command['id']}").json()["status"] == "succeeded"


def test_device_switch_failure_restores_selection_and_reports_reason(runtime_worker, api_client, monkeypatch):
    from yue2_studio_core.errors import StudioError, ErrorCode
    from yue2_studio_core.models import GenerationConfig
    worker = runtime_worker
    worker.manager.acquire(GenerationConfig())
    switch_devices(worker, monkeypatch)
    original = worker.manager._load
    def fail(config, key):
        if key.device_index == 1:
            raise StudioError(ErrorCode.CUDA_OOM, "target mock VRAM exhausted")
        return original(config, key)
    monkeypatch.setattr(worker.manager, "_load", fail)
    assert api_client.put("/api/v1/system/device", json={"device_index": 1}).status_code == 202
    asyncio.run(worker.run_command(worker.commands.claim(worker.worker_id, worker.session_id)))
    result = api_client.get("/api/v1/system/gpus").json()
    assert result["selected_index"] == result["active_index"] == 0
    assert result["switch_command"]["status"] == "failed"
    assert result["switch_command"]["error"]["error_code"] == "CUDA_OOM"
    assert result["switch_command"]["progress"]["stage"] == "restored"
    assert worker.manager.loaded
    assert api_client.put("/api/v1/system/device", json={"device_index": 9}).status_code == 422
    worker.write_heartbeat("stopped")
    assert api_client.put("/api/v1/system/device", json={"device_index": 1}).status_code == 422


def test_stopping_worker_rejects_generation_and_runtime_admission(runtime_worker, api_client):
    worker = runtime_worker
    registry_id = model_id(api_client, worker.settings.model_reference)
    before = len(worker.store.list_projects())
    worker.request_stop()
    response = api_client.post("/api/v1/generations", json={})
    assert response.status_code == 409 and "stopping" in response.json()["error_message"]
    assert len(worker.store.list_projects()) == before
    assert api_client.post(f"/api/v1/models/{registry_id}/load", json={}).status_code == 409
    assert api_client.put("/api/v1/system/device", json={"device_index": 0}).status_code == 409
    assert not api_client.get("/api/v1/system/runtime").json()["online"]
    asyncio.run(worker._shutdown(None))


def test_api_exit_requests_worker_shutdown_and_waits_for_release(runtime_worker, api_client, monkeypatch):
    from app import main
    from yue2_studio_core.models import GenerationConfig
    worker = runtime_worker
    worker.manager.acquire(GenerationConfig())
    monkeypatch.setattr(main, "settings_provider", lambda: worker.settings.model_copy(update={"worker_shutdown_timeout_seconds": 8}))
    async def run():
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        async with main.lifespan(api_client.app):
            assert worker.manager.loaded
        await asyncio.wait_for(task, 8)
    asyncio.run(run())
    state = api_client.get("/api/v1/system/runtime").json()
    assert not state["online"] and state["workers"][0]["state"] == "stopped"
    assert state["workers"][0]["shutdown"]["status"] == "completed"
    assert not worker.manager.loaded
