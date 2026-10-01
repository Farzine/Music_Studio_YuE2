"""Test fixtures.

Every test runs against a throwaway data directory so the developer's own
library is never touched, and the settings cache is cleared for each one.
"""
from __future__ import annotations

import os
import json
import struct
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "core"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))


@pytest.fixture()
def native_model_files():
    """Write an actual tiny safetensors layout, rather than pretending text is weights."""
    def write(path: Path, *, role: str = "model", latent_dim: int = 64):
        path.mkdir(parents=True, exist_ok=True)
        config = {"model_type": "yue2" if role == "model" else "yue2_vae", "latent_dim": latent_dim}
        (path / "config.json").write_text(json.dumps(config))
        header = json.dumps({"weight": {"dtype": "F16", "shape": [2], "data_offsets": [0, 4]}}).encode()
        (path / "model.safetensors").write_bytes(struct.pack("<Q", len(header)) + header + b"\0" * 4)
        return path
    return write


@pytest.fixture()
def runtime_manager(tmp_path, data_dir, native_model_files, monkeypatch):
    """Real installation preflight with an in-memory pipeline, no torch/GPU."""
    import time
    from types import SimpleNamespace
    from services.yue2_worker.model_manager.manager import ModelManager
    from yue2_studio_core.settings import Settings
    from yue2_studio_core.store import Store

    root = tmp_path / "runtime-models"
    model = native_model_files(root / "native")
    vae = native_model_files(root / "vae", role="vae")
    settings = Settings(data_dir=str(data_dir), yue2_models_dir=str(root),
                        yue2_model_path=str(model), yue2_vae_path=str(vae),
                        yue2_vae_legacy_path=str(root / "missing"), yue2_backend="native")
    manager = ModelManager(settings, Store(settings))
    monkeypatch.setattr(manager, "_check_runtime", lambda config, key: None)
    monkeypatch.setattr(manager, "_clear_cuda", lambda index: None)
    monkeypatch.setattr(manager, "_validate_device", lambda index: None)

    def load(config, key):
        manager._pipeline = SimpleNamespace(close=lambda: None, weights={"model": "fixture"})
        manager._key = key
        manager._loaded_at = manager._last_used = time.time()
        return manager._pipeline, True

    monkeypatch.setattr(manager, "_load", load)
    yield manager
    manager.end_use()
    # Test failures may deliberately leave a close error; OS resources and
    # leases must still be released without touching an actual CUDA device.
    if manager._pipeline is not None:
        for name in ("_model", "_vae", "_vllm_worker"):
            if hasattr(manager._pipeline, name):
                setattr(manager._pipeline, name, None)
        manager._pipeline.close = lambda: None
    manager._clear_cuda = lambda index: None
    manager.release()


@pytest.fixture()
def runtime_worker(runtime_manager, monkeypatch):
    from services.yue2_worker import worker as module
    from services.yue2_worker.adapters.mock import MockBackend
    from yue2_studio_core.settings import get_settings

    settings = runtime_manager.settings
    for name, value in {"YUE2_BACKEND": "native", "YUE2_MODELS_DIR": settings.yue2_models_dir,
                        "YUE2_MODEL_PATH": settings.yue2_model_path, "YUE2_VAE_PATH": settings.yue2_vae_path,
                        "YUE2_VAE_LEGACY_PATH": settings.yue2_vae_legacy_path}.items():
        monkeypatch.setenv(name, str(value))
    get_settings.cache_clear()
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "build_backend", lambda settings, manager, store: MockBackend(settings))
    monkeypatch.setattr(module, "gpu_snapshot", lambda index=None: {"available": True, "active_index": index, "devices": []})
    worker = module.Worker()
    worker.manager = runtime_manager
    worker.write_heartbeat("idle")
    return worker


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "data"
    directory.mkdir()
    monkeypatch.setenv("DATA_DIR", str(directory))
    monkeypatch.setenv("YUE2_BACKEND", "mock")
    monkeypatch.setenv("MAX_CONCURRENT_GPU_JOBS", "1")
    # Heartbeat-only mock workers cannot acknowledge an API lifespan request.
    monkeypatch.setenv("WORKER_SHUTDOWN_TIMEOUT_SECONDS", "0")
    from yue2_studio_core.settings import get_settings

    get_settings.cache_clear()
    yield directory
    get_settings.cache_clear()


@pytest.fixture()
def store(data_dir: Path):
    from yue2_studio_core.store import Store

    return Store()


@pytest.fixture()
def queue(store):
    from yue2_studio_core.queue import FilesystemJobQueue

    return FilesystemJobQueue(store, max_concurrent_gpu_jobs=1)


@pytest.fixture()
def api_client(data_dir: Path):
    """FastAPI test client with its dependency singletons rebuilt.

    Skipped in the worker environment, which deliberately has no FastAPI.
    """
    pytest.importorskip("fastapi", reason="this is the worker environment, which has no API dependencies")
    from fastapi.testclient import TestClient

    from app.core import deps

    for provider in (
        deps.settings_provider,
        deps.store_provider,
        deps.queue_provider,
        deps.capability_provider,
        deps.model_downloads_provider,
        deps.model_service_provider,
        deps.project_service_provider,
        deps.system_info_provider,
        deps.generation_service_provider,
    ):
        provider.cache_clear()

    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client

    for provider in (
        deps.settings_provider,
        deps.store_provider,
        deps.queue_provider,
        deps.capability_provider,
        deps.model_downloads_provider,
        deps.model_service_provider,
        deps.project_service_provider,
        deps.system_info_provider,
        deps.generation_service_provider,
    ):
        provider.cache_clear()


@pytest.fixture()
def sample_config() -> dict:
    return {
        "prompt": {
            "style": "warm piano pop, female vocal, 88 BPM",
            "lyrics": "[Verse]\nNeon fades along the lane\n[Chorus]\nLet the day come into view",
            "mode": "full",
        },
        "sampling": {"max_duration_seconds": 20.0, "seed": 4242},
    }


@pytest.fixture()
def hub_repository(monkeypatch):
    """Hub responses without network, model downloads or a GPU."""
    from types import SimpleNamespace
    from yue2_studio_core.model_metadata import GGUF_COMPANIONS
    from app.services.huggingface import HuggingFaceService

    configs = {
        "config.json": {"model_type": "yue2", "num_parameters": 1234},
        "sidecars/yue2-model-config.json": {
            "model_type": "yue2", "num_hidden_layers": 2, "num_key_value_heads": 2,
            "head_dim": 4, "max_position_embeddings": 128,
        },
        "sidecars/yue2-vae-config.json": {"model_type": "yue2_vae"},
    }
    names = ["custom-3b-q4_0.gguf", "model.safetensors", "README.md", *GGUF_COMPANIONS]
    info = SimpleNamespace(sha="a" * 40, siblings=[SimpleNamespace(rfilename=n, size=128, lfs=None) for n in names],
                           card_data={"description": "Fixture model", "license": "apache-2.0"})
    info.siblings.append(SimpleNamespace(rfilename="config.json", size=128, lfs=None))
    calls = []

    def model_info(repo_id, **kwargs):
        calls.append((repo_id, kwargs))
        return info

    api = SimpleNamespace(model_info=model_info,
                          list_repo_refs=lambda repo: SimpleNamespace(
                              branches=[SimpleNamespace(name="main", target_commit="a" * 40)],
                              tags=[SimpleNamespace(name="v1", target_commit="b" * 40)]),
                          list_models=lambda **kwargs: [SimpleNamespace(id="owner/repository")])
    monkeypatch.setattr("app.services.huggingface.HfApi", lambda: api)
    monkeypatch.setattr(HuggingFaceService, "_json", lambda self, repo, commit, name, files: configs.get(name, {}) if name in files else {})
    return SimpleNamespace(info=info, configs=configs, api=api, calls=calls)


@pytest.fixture()
def download_package(tmp_path, native_model_files, monkeypatch):
    """Tiny, real GGUF/safetensors structures served by a fake SDK transfer."""
    from types import SimpleNamespace
    from yue2_studio_core.model_metadata import GGUF_COMPANIONS
    from app.services.huggingface import HuggingFaceService
    import hashlib

    source = native_model_files(tmp_path / "source")
    def gguf(name, kind):
        def string(value):
            value = value.encode()
            return struct.pack("<Q", len(value)) + value
        metadata = [("general.architecture", "audiocpp"), ("audiocpp.model_spec.family", "yue2")]
        payload = b"GGUF" + struct.pack("<IQQ", 3, 1, len(metadata))
        for key, value in metadata:
            payload += string(key) + struct.pack("<I", 8) + string(value)
        payload += string("weight") + struct.pack("<IQIQ", 1, 32 if kind == 2 else 2, kind, 0)
        payload += b"\0" * (-len(payload) % 32)
        (source / name).write_bytes(payload + b"\0" * (18 if kind == 2 else 4))
    gguf("custom.gguf", 2)
    gguf("yue2-vae-f16.gguf", 1)
    for name in GGUF_COMPANIONS:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".json"):
            path.write_text(json.dumps({"model_type": "yue2_vae" if "vae-config" in name else "yue2"}))
        elif name.endswith(".tiktoken"):
            path.write_bytes(b"tokenizer")
    (source / "README.md").write_text("Fixture repository")
    files = [{"name": str(p.relative_to(source)), "bytes": p.stat().st_size,
              "extension": p.suffix, "checksum_sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(source.rglob("*")) if p.is_file()]
    inspection = {"repo_id": "owner/repository", "revision": "a" * 40, "requested_revision": "main",
                  "files": files, "candidates": [{"model": {"filename": f["name"]}} for f in files
                                                  if f["extension"] in {".gguf", ".safetensors"}], "warnings": []}
    monkeypatch.setattr(HuggingFaceService, "inspect", lambda self, *args: json.loads(json.dumps(inspection)))
    calls = []
    def transfer(repo_id, filename, *, revision, local_dir, callback, force_download=False):
        calls.append((filename, revision, force_download))
        content = (source / filename).read_bytes()
        path = local_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        callback(0, len(content))
        with path.open("wb") as stream:
            mid = len(content) // 2
            stream.write(content[:mid]); callback(mid, len(content))
            stream.write(content[mid:]); callback(len(content), len(content))
        return str(path)
    monkeypatch.setattr("app.services.model_downloads.download_file", transfer)
    return SimpleNamespace(source=source, inspection=inspection, calls=calls, transfer=transfer)
