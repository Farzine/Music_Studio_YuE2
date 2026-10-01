"""Download/retry/cleanup endpoints with tiny real files and mocked network."""
from pathlib import Path

import pytest

from app.core.deps import model_downloads_provider


@pytest.mark.parametrize("mode", ["single", "selected", "repository"])
def test_download_modes_register_only_complete_content(api_client, download_package, monkeypatch, tmp_path, mode):
    downloads = model_downloads_provider()
    # Keep all destinations away from the developer's actual installed weights.
    monkeypatch.setattr(downloads.settings, "yue2_models_dir", str(tmp_path / "models"))
    response = api_client.post("/api/v1/models/downloads", json={
        "repo_id": "owner/repository", "filename": "custom.gguf", "revision": "main", "mode": mode,
    })
    assert response.status_code == 202, response.json()
    queued = response.json()
    assert queued["status"] == "queued"
    result = api_client.get(f"/api/v1/models/downloads/{queued['id']}").json()
    assert result["status"] == "complete" and result["registry_id"]
    assert result["percentage"] == 100 and result["total_bytes"] == result["downloaded_bytes"]
    assert Path(result["path"]).is_dir()
    inspected = api_client.get(f"/api/v1/models/{result['registry_id']}")
    assert inspected.status_code == 200
    assert api_client.post(f"/api/v1/models/downloads/{queued['id']}/retry").status_code == 409
    assert api_client.delete(f"/api/v1/models/downloads/{queued['id']}/partial").status_code == 409


def test_failed_transfer_cleanup_and_retry_preserve_commit(api_client, download_package, monkeypatch, tmp_path):
    downloads = model_downloads_provider()
    monkeypatch.setattr(downloads.settings, "yue2_models_dir", str(tmp_path / "models"))
    def interrupted(*args, **kwargs):
        (kwargs["local_dir"] / "partial").write_bytes(b"partial")
        raise OSError("interrupted")
    monkeypatch.setattr("app.services.model_downloads.download_file", interrupted)
    response = api_client.post("/api/v1/models/downloads", json={"repo_id": "owner/repository", "filename": "model.safetensors"})
    job_id = response.json()["id"]
    failed = api_client.get(f"/api/v1/models/downloads/{job_id}").json()
    assert failed["status"] == "failed" and failed["error"]
    assert failed["path"] is None and failed["registry_id"] is None
    assert api_client.delete(f"/api/v1/models/downloads/{job_id}/partial").json()["partial_bytes"] == 0
    monkeypatch.setattr("app.services.model_downloads.download_file", download_package.transfer)
    retry = api_client.post(f"/api/v1/models/downloads/{job_id}/retry")
    assert retry.status_code == 202 and retry.json()["attempt"] == 2
    complete = api_client.get(f"/api/v1/models/downloads/{job_id}").json()
    assert complete["status"] == "complete" and complete["revision"] == failed["revision"]


def test_invalid_file_selection_never_queues(api_client, download_package, monkeypatch, tmp_path):
    downloads = model_downloads_provider()
    monkeypatch.setattr(downloads.settings, "yue2_models_dir", str(tmp_path / "models"))
    response = api_client.post("/api/v1/models/downloads", json={
        "repo_id": "owner/repository", "filename": "model.safetensors", "mode": "selected", "selected_files": ["../config.json"],
    })
    assert response.status_code == 422
    assert api_client.get("/api/v1/models/downloads").json() == {"items": []}
