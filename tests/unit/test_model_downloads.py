"""Download boundaries and the hardware estimate, without network or GPU."""
from __future__ import annotations

from types import SimpleNamespace
from contextlib import nullcontext
import sys

import pytest

from yue2_studio_core.errors import ValidationError
from yue2_studio_core.queue import FilesystemJobQueue
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store
from yue2_studio_core.model_registry import ModelRegistry

from app.services.capabilities import CapabilityService
from app.services.model_downloads import ModelDownloads
from app.services.system_info import SystemInfoService
from services.yue2_worker.model_manager.manager import ModelManager
from yue2_studio_core.models import GenerationConfig


def test_gguf_download_is_registered_only_when_companions_are_present(tmp_path, monkeypatch):
    cli = tmp_path / "audiocpp_cli"
    cli.touch()
    cli.chmod(0o755)
    settings = Settings(data_dir=str(tmp_path / "data"), yue2_model_path=str(tmp_path / "models" / "YuE2-3B"),
                        yue2_models_dir=str(tmp_path / "models"), audiocpp_cli_path=str(cli))
    store = Store(settings)
    downloads = ModelDownloads(settings, store)
    names = [
        "yue2-3b-q8_0.gguf", "yue2-vae-f16.gguf",
        "sidecars/yue2-model-config.json", "sidecars/yue2-generation-config.json",
        "sidecars/yue2-qwen.tiktoken", "sidecars/yue2-vae-config.json",
    ]
    info = SimpleNamespace(sha="a" * 40, siblings=[SimpleNamespace(rfilename=name, size=3) for name in names])
    monkeypatch.setattr("app.services.model_downloads.HfApi", lambda: SimpleNamespace(model_info=lambda *a, **kw: info))

    def fake_download(repo_id, filename, *, revision, local_dir):
        path = local_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")
        if filename.endswith(".json"):
            path.write_text('{"model_type":"yue2_vae"}' if "vae-config" in filename else '{"model_type":"yue2"}')
        return str(path)

    monkeypatch.setattr("app.services.model_downloads.hf_hub_download", fake_download)
    with pytest.raises(ValidationError):
        downloads.start("audio-cpp/Yue2-3B-GGUF", "../escape.gguf", None)
    job = downloads.start("audio-cpp/Yue2-3B-GGUF", names[0], "main")
    downloads.run(job["id"])
    complete = downloads.get(job["id"])
    assert complete["status"] == "complete"
    # Completion registers durably, without needing an inventory request first.
    assert ModelRegistry(settings, store).path.is_file()
    entry = next(item for item in CapabilityService(settings).local_models() if item["id"] == complete["path"])
    assert entry["present"] and entry["format"] == "gguf"
    assert entry["registration_status"] == "registered"
    assert entry["commit_hash"] == "a" * 40


def test_failed_transfer_does_not_register_partial_weights(tmp_path, monkeypatch):
    settings = Settings(data_dir=str(tmp_path / "data"), yue2_models_dir=str(tmp_path / "models"))
    downloads = ModelDownloads(settings, Store(settings))
    info = SimpleNamespace(sha="a" * 40, siblings=[SimpleNamespace(rfilename="other.gguf", size=3)])
    monkeypatch.setattr("app.services.model_downloads.HfApi", lambda: SimpleNamespace(model_info=lambda *a, **kw: info))

    def interrupted(repo_id, filename, *, revision, local_dir):
        local_dir.mkdir(parents=True)
        (local_dir / (filename + ".part")).write_bytes(b"partial")
        raise OSError("Network interrupted")

    monkeypatch.setattr("app.services.model_downloads.hf_hub_download", interrupted)
    job = downloads.start("owner/repository", "other.gguf", None)
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "failed"
    assert not downloads.registry.path.exists()
    assert not list(settings.models_path.rglob("studio-model.json"))


def test_recommendation_uses_selected_gpu_and_headroom(tmp_path, monkeypatch):
    settings = Settings(data_dir=str(tmp_path / "data"))
    store = Store(settings)
    service = SystemInfoService(settings, store, FilesystemJobQueue(store))
    monkeypatch.setattr(service, "devices", lambda: {
        "selected_index": 1,
        "devices": [{"index": 1, "memory_total_bytes": 12 * 1024**3,
                     "memory_free_bytes": 10 * 1024**3, "processes": []}],
    })
    monkeypatch.setattr(service, "worker_state", lambda: {"workers": []})
    answer = service.model_recommendation()
    assert answer["recommended"]["label"] == "Q4_0"
    assert answer["max_parameters"] == 3_000_000_000
    assert not answer["variants"][2]["runnable"]


def test_idle_gpu_switch_closes_the_previous_pipeline(tmp_path, monkeypatch):
    settings = Settings(data_dir=str(tmp_path / "data"))
    store = Store(settings)
    manager = ModelManager(settings, store=store)
    closed = []
    manager._pipeline = SimpleNamespace(close=lambda: closed.append(True))
    manager._key = manager.key_for(GenerationConfig())
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(
        device=lambda index: nullcontext(), empty_cache=lambda: None, ipc_collect=lambda: None,
    )))
    store.write_runtime_settings({"device_index": 1})
    assert manager.release_if_device_changed()
    assert closed == [True]
    assert not manager.loaded
