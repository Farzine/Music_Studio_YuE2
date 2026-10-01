def test_browse_validate_and_register_use_only_trusted_model_roots(runtime_worker, api_client, tmp_path):
    root = runtime_worker.settings.models_path
    listing = api_client.get("/api/v1/models/local/browse", params={"path": str(root)}).json()
    assert str(root) in listing["roots"] and listing["path"] == str(root)
    path = root / "native" / "model.safetensors"
    reply = api_client.post("/api/v1/models/local/validate", json={"path": str(path), "kind": "file"})
    assert reply.status_code == 200 and reply.json()["exists"]
    reply = api_client.post("/api/v1/models/local/register", json={"path": str(path), "kind": "file"})
    assert reply.status_code == 200 and reply.json()["model"]["role"] == "model"
    reply = api_client.post("/api/v1/models/local/register", json={"path": runtime_worker.settings.vae_reference, "kind": "directory"})
    assert reply.status_code == 200 and reply.json()["model"]["role"] == "vae"
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / ".private.gguf").write_bytes(b"private")
    listing = api_client.get("/api/v1/models/local/browse", params={"path": str(root)}).json()
    assert "escape" not in {i["name"] for i in listing["items"]}
    for unsafe in (outside, root / "escape", root / ".private.gguf"):
        assert api_client.post("/api/v1/models/local/validate", json={"path": str(unsafe), "kind": "directory"}).status_code == 422
    assert api_client.post("/api/v1/models/local/validate", json={"path": str(root / "missing"), "kind": "file"}).status_code == 404
    assert api_client.post("/api/v1/models/local/validate", json={"path": str(root / "native" / "config.json"), "kind": "file"}).status_code == 422
    assert api_client.get("/api/v1/models/local/browse", params={"path": "../"}).status_code == 422


def test_invalid_installation_marker_returns_actionable_error(runtime_worker, api_client):
    root = runtime_worker.settings.models_path / "native"
    (root / "studio-model.json").write_text('{"role": "invalid"}')
    reply = api_client.post("/api/v1/models/local/register", json={"path": str(root), "kind": "directory"})
    assert reply.status_code == 422 and "metadata" in reply.text


def test_empty_model_path_does_not_expose_repository_root(runtime_worker, api_client, monkeypatch):
    from yue2_studio_core.settings import repo_root
    monkeypatch.setattr(runtime_worker.settings, "yue2_model_path", "")
    monkeypatch.setattr(runtime_worker.settings, "model_browser_roots", [""])
    roots = api_client.get("/api/v1/models/local/browse").json()["roots"]
    assert str(repo_root()) not in roots
    assert api_client.get("/api/v1/models/local/browse", params={"path": str(repo_root())}).status_code == 422
