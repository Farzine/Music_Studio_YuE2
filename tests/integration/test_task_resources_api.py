import asyncio
import json

import pytest

from app.core.deps import model_downloads_provider
from app.services.system_info import SystemInfoService
from yue2_studio_core.model_metadata import GGUF_COMPANIONS
from yue2_studio_core.models import GenerationConfig


def visible_gpu(monkeypatch):
    monkeypatch.setattr(SystemInfoService, "devices", lambda self, **kwargs: {
        "selected_index": 0, "devices": [{"index": index, "name": f"Fixture GPU {index}", "selectable": True,
        "cuda_available": True, "memory_free_bytes": 24 * 2**30, "memory_total_bytes": 24 * 2**30,
        "bf16_supported": True, "fp16_supported": True} for index in (0, 3)]})


def test_task_options_keep_model_vae_independent_and_gpu_is_recorded(runtime_worker, api_client, monkeypatch, native_model_files, sample_config):
    visible_gpu(monkeypatch)
    worker = runtime_worker
    incompatible = native_model_files(worker.settings.models_path / "incompatible-vae", role="vae", latent_dim=128)
    payload = {"model": {"checkpoint": worker.settings.model_reference, "vae": "standard", "device_index": 3}}
    options = api_client.post("/api/v1/generation/options", json=payload).json()
    assert options["valid"], options
    assert any(o["value"] == worker.settings.model_reference and o["enabled"] for o in options["models"])
    assert not next(o for o in options["vaes"] if o["value"] == str(incompatible))["enabled"]
    reply = api_client.post("/api/v1/generations", json={"config": {**sample_config, **payload}})
    assert reply.status_code == 201, reply.text
    config = reply.json()["generation"]["config"]["model"]
    assert config["checkpoint"] == worker.settings.model_reference
    assert config["vae"] == "standard" and config["device_index"] == 3
    assert worker.store.device_index() == 0
    payload["model"]["vae"] = str(incompatible)
    assert api_client.post("/api/v1/generation/options", json=payload).json()["valid"] is False
    assert api_client.post("/api/v1/generations", json={"config": {**sample_config, **payload}}).status_code == 409
    payload["model"].update(vae="standard", device_index=9)
    assert api_client.post("/api/v1/generations", json={"config": {**sample_config, **payload}}).status_code == 422


def test_native_vae_download_registers_decoder_role_and_restores_inventory(api_client, download_package, monkeypatch, tmp_path):
    import hashlib
    downloads = model_downloads_provider()
    monkeypatch.setattr(downloads.settings, "yue2_models_dir", str(tmp_path / "models"))
    path = download_package.source / "config.json"
    path.write_text(json.dumps({"model_type": "yue2_vae", "latent_dim": 64}))
    for file in download_package.inspection["files"]:
        if file["name"] == "config.json":
            file.update(bytes=path.stat().st_size, checksum_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    candidate = next(c for c in download_package.inspection["candidates"] if c["model"]["filename"] == "model.safetensors")
    candidate["model"].update(role="vae", format="safetensors")
    reply = api_client.post("/api/v1/models/downloads", json={"repo_id": "owner/repository", "filename": "model.safetensors"})
    assert reply.status_code == 202, reply.text
    job = api_client.get(f'/api/v1/models/downloads/{reply.json()["id"]}').json()
    assert job["status"] == "complete", job
    installed = [m for m in api_client.get("/api/v1/models").json()["items"] if m["id"] == job["path"]]
    assert len(installed) == 1 and installed[0]["role"] == "vae"
    assert installed[0]["validation_status"] == "validated" and installed[0]["inference_ready"]


def test_gguf_requires_explicit_ui_vae_but_preserves_legacy_api_alias(runtime_worker, api_client, monkeypatch, download_package):
    import shutil
    from yue2_studio_core.store import write_json_atomic
    visible_gpu(monkeypatch)
    root = runtime_worker.settings.models_path / "gguf"
    shutil.copytree(download_package.source, root)
    write_json_atomic(root / "studio-model.json", {"filename": "custom.gguf"})
    monkeypatch.setattr("app.services.capabilities.audiocpp_available", lambda settings: True)
    model = {"checkpoint": str(root), "vae": "standard"}
    options = api_client.post("/api/v1/generation/options", json={"model": model}).json()
    bundled = str(root / GGUF_COMPANIONS[0])
    assert any(v["value"] == bundled for v in options["vaes"])
    assert not options["valid"] and any("explicitly" in issue for issue in options["issues"])
    runtime_worker.manager.verify_files(GenerationConfig(model=model))
    from services.yue2_worker.adapters.audiocpp import AudioCppBackend
    monkeypatch.setattr("services.yue2_worker.adapters.audiocpp.audiocpp_available", lambda settings: True)
    adapter = AudioCppBackend(runtime_worker.settings, runtime_worker.store, 3)
    asyncio.run(adapter.validate_config(GenerationConfig(model=model)))
    model["vae"] = bundled
    runtime_worker.manager.verify_files(GenerationConfig(model=model))
    asyncio.run(adapter.validate_config(GenerationConfig(model=model)))
    model["vae"] = runtime_worker.settings.vae_reference
    bad = GenerationConfig(model=model)
    from yue2_studio_core.errors import StudioError
    with pytest.raises(StudioError, match="bundled F16"):
        runtime_worker.manager.verify_files(bad)
    with pytest.raises(StudioError, match="bundled F16"):
        asyncio.run(adapter.validate_config(bad))


def test_schema_precision_capabilities_follow_task_gpu(runtime_worker, api_client, monkeypatch):
    visible_gpu(monkeypatch)
    devices = SystemInfoService.devices
    def with_precision(self, **kwargs):
        result = devices(self, **kwargs)
        for device in result["devices"]:
            device["compute_capability"] = "7.5" if device["index"] == 0 else "9.0"
        return result
    monkeypatch.setattr(SystemInfoService, "devices", with_precision)
    old = api_client.get("/api/v1/generation/schema", params={"device_index": 0}).json()
    target = api_client.get("/api/v1/generation/schema", params={"device_index": 3}).json()
    assert not old["capabilities"]["quantization_fp8"]["supported"]
    assert target["capabilities"]["quantization_fp8"]["supported"]
    assert runtime_worker.store.device_index() == 0


def test_standalone_gguf_vae_preview_is_rejected(api_client, download_package):
    from yue2_studio_core.errors import ValidationError
    downloads = model_downloads_provider()
    candidate = next(c for c in download_package.inspection["candidates"] if c["model"]["filename"] == "custom.gguf")
    candidate["model"].update(role="vae", format="gguf")
    with pytest.raises(ValidationError, match="bundled F16"):
        downloads.hub.preview(download_package.inspection, "custom.gguf")


def test_gguf_model_and_bundled_vae_become_selectable_when_cli_installed(runtime_worker, api_client, monkeypatch, download_package):
    import shutil
    from yue2_studio_core.store import write_json_atomic
    visible_gpu(monkeypatch)
    root = runtime_worker.settings.models_path / "downloaded-gguf"
    shutil.copytree(download_package.source, root)
    write_json_atomic(root / "studio-model.json", {"filename": "custom.gguf"})
    available = False
    monkeypatch.setattr("app.services.capabilities.audiocpp_available", lambda settings: available)
    # Hardware assessment uses the same live availability input.
    monkeypatch.setattr("app.services.system_info.audiocpp_available", lambda settings: available)
    config = {"model": {"checkpoint": str(root), "vae": str(root / GGUF_COMPANIONS[0]), "device_index": 0}}
    first = api_client.post("/api/v1/generation/options", json=config).json()
    assert not next(m for m in first["models"] if m["value"] == str(root))["enabled"]
    available = True
    second = api_client.post("/api/v1/generation/options", json=config).json()
    assert next(m for m in second["models"] if m["value"] == str(root))["enabled"]
    assert next(v for v in second["vaes"] if v["value"] == config["model"]["vae"])["enabled"]
    assert second["valid"], second["issues"]
