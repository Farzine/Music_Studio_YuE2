"""Inspection/selection endpoints preserve legacy browsing and never queue work."""
from app.core.deps import capability_provider, system_info_provider


def gpu_view(monkeypatch):
    system = system_info_provider()
    monkeypatch.setattr(capability_provider(), "local_models", lambda: [])
    monkeypatch.setattr(system, "worker_state", lambda: {"workers": [{"online": True, "backend": "native"}]})
    monkeypatch.setattr(system, "devices", lambda **kw: {
        "selected_index": 0, "devices": [{"index": 0, "selectable": True, "cuda_available": True,
                                           "memory_total_bytes": 24 * 2**30, "memory_free_bytes": 20 * 2**30}],
    })


def test_inspect_preview_discover_and_legacy_browse(api_client, hub_repository, monkeypatch):
    gpu_view(monkeypatch)
    reply = api_client.post("/api/v1/models/hub/inspect", json={"repo_id": "owner/repository", "revision": "v1"})
    assert reply.status_code == 200
    inspection = reply.json()
    assert inspection["revision"] == "a" * 40 and "candidate_contexts" not in inspection
    assert len(inspection["by_gpu"]) == 1 and inspection["assessments"]
    assert all(not a["runnable"] and not a["inference_ready"] for a in inspection["assessments"])
    assert not any(a["filename"].startswith("yue2-vae-") for a in inspection["assessments"])
    preview = api_client.post("/api/v1/models/hub/preview", json={
        "repo_id": "owner/repository", "revision": inspection["revision"], "filename": "custom-3b-q4_0.gguf",
    })
    assert preview.status_code == 200 and len(preview.json()["files"]) == 6
    assert preview.json()["assessment"]["estimate"]["vae_size_known"]
    assert preview.json()["assessment"]["estimate"]["kv_source"] == "model_config_full_context_two_cfg_branches"
    whole = api_client.post("/api/v1/models/hub/preview", json={
        "repo_id": "owner/repository", "filename": "model.safetensors", "mode": "repository",
    })
    assert whole.status_code == 200 and len(whole.json()["files"]) == len(inspection["files"])
    legacy = api_client.get("/api/v1/models/hub", params={"repo_id": "owner/repository"})
    assert legacy.status_code == 200 and set(legacy.json()) == {"repo_id", "revision", "files"}
    discovery = api_client.get("/api/v1/models/hub/discover", params={"limit": 1})
    assert discovery.status_code == 200 and discovery.json()["items"][0]["assessments"]
    assert api_client.get("/api/v1/models/downloads").json() == {"items": []}


def test_invalid_repo_revision_file_gpu_and_mode_are_actionable(api_client, hub_repository, monkeypatch):
    gpu_view(monkeypatch)
    for payload in ({"repo_id": "https://bad"}, {"repo_id": "owner/repository", "revision": "../main"},
                    {"repo_id": "owner/repository", "device_index": 99}):
        response = api_client.post("/api/v1/models/hub/inspect", json=payload)
        assert response.status_code == 422 and response.json()["error_message"]
    response = api_client.post("/api/v1/models/hub/preview", json={"repo_id": "owner/repository", "filename": "absent.gguf"})
    assert response.status_code == 404 and "absent.gguf" in response.json()["error_message"]
    response = api_client.post("/api/v1/models/hub/preview", json={"repo_id": "owner/repository", "filename": "../x.gguf"})
    assert response.status_code == 422
    response = api_client.post("/api/v1/models/hub/preview", json={"repo_id": "owner/repository", "filename": "model.safetensors", "mode": "invalid"})
    assert response.status_code == 422
    assert api_client.get("/api/v1/models/hub/discover", params={"limit": 21}).status_code == 422


def test_gpu_assessments_are_read_only_and_pinned_preview_keeps_exact_content(api_client, hub_repository, monkeypatch):
    from app.core.deps import store_provider
    gpu_view(monkeypatch)
    monkeypatch.setattr(system_info_provider(), "devices", lambda **kw: {
        "selected_index": 0, "devices": [
            {"index": index, "selectable": True, "cuda_available": True,
             "memory_total_bytes": size * 2**30, "memory_free_bytes": size * 2**30}
            for index, size in ((0, 24), (1, 8))],
    })
    before = store_provider().device_index()
    inspection = api_client.post("/api/v1/models/hub/inspect", json={
        "repo_id": "owner/repository", "revision": "v1", "device_index": 1,
    }).json()
    assert inspection["device_index"] == 1
    assert all(item["device_index"] == 1 for item in inspection["assessments"])
    reply = api_client.post("/api/v1/models/hub/preview", json={
        "repo_id": inspection["repo_id"], "revision": inspection["revision"], "device_index": 1,
        "filename": "custom-3b-q4_0.gguf", "mode": "selected", "selected_files": ["sidecars/yue2-model-config.json"],
    })
    assert reply.status_code == 200
    preview = reply.json()
    assert preview["revision"] == inspection["revision"]
    assert preview["device_index"] == 1 and preview["assessment"]["device_index"] == 1
    assert {f["name"] for f in preview["files"]} == {"custom-3b-q4_0.gguf", "sidecars/yue2-model-config.json"}
    assert preview["missing_required_files"] and preview["safety_margin_bytes"] > 0
    discovery = api_client.get("/api/v1/models/hub/discover", params={"limit": 1, "device_index": 1}).json()
    assert discovery["items"][0]["device_index"] == 1
    assert store_provider().device_index() == before
    assert api_client.get("/api/v1/models/downloads").json() == {"items": []}


def test_completed_package_repair_and_delete_missing_installation(api_client, download_package):
    from pathlib import Path
    import shutil
    reply = api_client.post("/api/v1/models/downloads", json={"repo_id": "owner/repository", "filename": "custom.gguf"})
    job = api_client.get(f'/api/v1/models/downloads/{reply.json()["id"]}').json()
    registry_id = job["registry_id"]
    root = Path(job["path"])
    (root / "yue2-vae-f16.gguf").unlink()
    preview = api_client.get(f"/api/v1/models/{registry_id}/repair-preview")
    assert preview.status_code == 200, preview.text
    repaired = api_client.post(f"/api/v1/models/{registry_id}/repair", json={"confirmation_token": preview.json()["confirmation_token"]})
    assert repaired.status_code == 202, repaired.text
    assert api_client.get(f'/api/v1/models/downloads/{repaired.json()["id"]}').json()["status"] == "complete"
    assert (root / "yue2-vae-f16.gguf").exists()
    shutil.rmtree(root)
    deletion = api_client.get(f"/api/v1/models/{registry_id}/deletion-preview").json()
    assert deletion["can_delete"] and deletion["estimated_reclaimed_bytes"] == 0
    response = api_client.request("DELETE", f"/api/v1/models/{registry_id}", json={
        "confirmation_token": deletion["confirmation_token"], "confirmed_path": deletion["path"]})
    assert response.status_code == 200 and response.json()["complete"]
    assert not any(m["registry_id"] == registry_id for m in api_client.get("/api/v1/models").json()["items"])
