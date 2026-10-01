"""Worker lifecycle checks run in normal CI without YuE2, torch or a GPU."""
import json
import threading
from types import SimpleNamespace

import pytest

from yue2_studio_core.errors import ConflictError, ErrorCode, StudioError
from yue2_studio_core.model_files import model_file_leases
from yue2_studio_core.model_registry import ModelRegistry
from yue2_studio_core.model_validator import validate_installation
from yue2_studio_core.models import GenerationConfig


def test_load_reuse_use_idle_unload_and_file_leases(runtime_manager):
    manager = runtime_manager
    config = GenerationConfig()
    assert manager.state()["lifecycle"] == "UNLOADED"
    pipeline, loaded_now = manager.acquire(config, 1)
    assert loaded_now and manager.state()["lifecycle"] == "LOADED"
    assert manager.state()["device_index"] == 1
    with pytest.raises(ConflictError):
        with model_file_leases(manager._store, [manager.resolve_model(config)], shared=False, blocking=False):
            pass
    manager.begin_use()
    assert manager.state()["lifecycle"] == "IN_USE"
    assert manager.state()["idle_seconds"] is None
    with pytest.raises(ConflictError):
        manager.release()
    with pytest.raises(ConflictError):
        manager.acquire(config)
    manager.end_use()
    assert manager.state()["lifecycle"] == "IDLE"
    reused, loaded_now = manager.acquire(config, 1)
    assert reused is pipeline and not loaded_now
    manager.release()
    assert manager.state()["lifecycle"] == "UNLOADED"
    with model_file_leases(manager._store, [manager.resolve_model(config)], shared=False, blocking=False):
        pass


@pytest.mark.parametrize("operation, transition", [("load", "LOADING"), ("close", "UNLOADING")])
def test_snapshots_remain_readable_during_blocking_runtime_calls(runtime_manager, monkeypatch, operation, transition):
    manager = runtime_manager
    entered, finish = threading.Event(), threading.Event()
    original = manager._load

    def block(*args):
        entered.set()
        assert finish.wait(5)
        if operation == "load":
            return original(*args)

    if operation == "close":
        manager.acquire(GenerationConfig())
        manager._pipeline.close = block
    else:
        monkeypatch.setattr(manager, "_load", block)
    errors = []
    def run():
        try:
            manager.acquire(GenerationConfig()) if operation == "load" else manager.release()
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(3)
        assert manager.state()["lifecycle"] == transition
        # Version introspection also avoids the runtime mutation lock.
        manager.runtime_versions()
    finally:
        finish.set()
        thread.join(5)
    assert not thread.is_alive() and not errors


def test_failed_load_releases_file_leases_and_can_retry(runtime_manager, monkeypatch):
    manager = runtime_manager
    original = manager._load
    def fail(*args):
        raise StudioError(ErrorCode.MODEL_LOAD_FAILED, "mock load error")
    monkeypatch.setattr(manager, "_load", fail)
    with pytest.raises(StudioError):
        manager.acquire(GenerationConfig())
    assert manager.state()["lifecycle"] == "LOAD_FAILED"
    assert not manager.loaded
    with model_file_leases(manager._store, [manager.settings.model_reference], shared=False, blocking=False):
        pass
    monkeypatch.setattr(manager, "_load", original)
    manager.acquire(GenerationConfig())
    assert manager.loaded


@pytest.mark.parametrize("failure", ["close", "cuda"])
def test_failed_cleanup_is_observable_and_blocks_reload(runtime_manager, monkeypatch, failure):
    manager = runtime_manager
    manager.acquire(GenerationConfig())
    def fail(*args):
        raise RuntimeError("mock cleanup error")
    if failure == "close":
        manager._pipeline.close = fail
    else:
        monkeypatch.setattr(manager, "_clear_cuda", fail)
    with pytest.raises(StudioError) as caught:
        manager.release()
    assert caught.value.code is ErrorCode.MODEL_UNLOAD_FAILED
    assert manager.state()["lifecycle"] == "UNLOAD_FAILED"
    assert manager.state()["loaded"] is (failure == "close")
    assert not manager.state()["residency_known"]
    manager.settings.model_idle_unload_seconds = 1
    manager._last_used = 0
    assert manager.maybe_unload_idle() is False
    manager._store.write_runtime_settings({"device_index": 1})
    assert manager.release_if_device_changed() is False
    with pytest.raises(ConflictError):
        manager.acquire(GenerationConfig())
    with pytest.raises(ConflictError):
        manager.begin_use()
    with pytest.raises(ConflictError):
        with model_file_leases(manager._store, [manager.settings.model_reference], shared=False, blocking=False):
            pass
    if manager._pipeline is not None:
        manager._pipeline.close = lambda: None
    monkeypatch.setattr(manager, "_clear_cuda", lambda index: None)
    manager.release()
    assert manager.state()["lifecycle"] == "UNLOADED"


def test_worker_path_and_resident_reuse_honor_validation_reports(runtime_manager):
    manager = runtime_manager
    registry = ModelRegistry(manager.settings, manager._store)
    entry = registry.register(manager.settings.model_reference)
    registry.save_validation(validate_installation(entry))
    manager.acquire(GenerationConfig())
    weights = manager.settings.models_path / "native" / "model.safetensors"
    weights.write_bytes(weights.read_bytes() + b"changed")
    with pytest.raises(StudioError, match="changed since validation"):
        manager.acquire(GenerationConfig())
    manager.release()
    registry.save_validation(validate_installation(registry.describe(str(weights.parent))))
    with pytest.raises(StudioError):
        manager.acquire(GenerationConfig())
    assert manager.state()["lifecycle"] == "LOAD_FAILED"


def test_incompatible_vae_fails_without_loading(runtime_manager):
    manager = runtime_manager
    path = manager.settings.models_path / "vae" / "config.json"
    path.write_text(json.dumps({"model_type": "yue2_vae", "latent_dim": 128}))
    with pytest.raises(StudioError, match="latent width"):
        manager.acquire(GenerationConfig())
    assert not manager.loaded and manager.state()["lifecycle"] == "LOAD_FAILED"


def test_external_process_does_not_claim_verified_gpu_residency(runtime_manager):
    manager = runtime_manager
    manager.external_started(GenerationConfig(), 1, 12345)
    state = manager.state()
    assert state["lifecycle"] == "IN_USE" and state["process_id"] == 12345
    assert state["residency_mode"] == "per_job" and not state["residency_known"] and not state["loaded"]
    with pytest.raises(ConflictError):
        manager.acquire(GenerationConfig())
    manager.external_finished()
    assert manager.state()["lifecycle"] == "UNLOADED" and manager.state()["process_id"] is None


def test_runtime_memory_guard_uses_shared_margin_and_handles_missing_gpu(runtime_manager, monkeypatch):
    from services.yue2_worker.model_manager.manager import ModelManager
    manager = runtime_manager
    fake = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, device_count=lambda: 1,
                         get_device_properties=lambda index: SimpleNamespace(major=8, minor=6),
                         mem_get_info=lambda index: (2**30, 24 * 2**30)))
    monkeypatch.setitem(__import__("sys").modules, "torch", fake)
    monkeypatch.setattr(manager, "_validate_device", ModelManager._validate_device)
    config = GenerationConfig()
    with pytest.raises(StudioError) as caught:
        ModelManager._check_runtime(manager, config, manager.key_for(config))
    assert caught.value.code is ErrorCode.CUDA_OOM
    assert caught.value.details["assessment"]["excess_bytes"] > 0
    fake.cuda.is_available = lambda: False
    with pytest.raises(StudioError, match="unavailable"):
        ModelManager._check_runtime(manager, config, manager.key_for(config))


def test_pinned_native_factory_materializes_weights_and_reports_cpu_moves(runtime_manager, monkeypatch):
    import sys
    from services.yue2_worker.model_manager.manager import ModelManager
    manager = runtime_manager
    gpu = SimpleNamespace(type="cuda", index=0)
    cpu = SimpleNamespace(type="cpu", index=None)
    parameter = SimpleNamespace(device=gpu)
    pipeline = SimpleNamespace(_model=None, _vae=None, weights={}, close=lambda: None)
    pipeline.close = lambda: setattr(pipeline, "_model", None)
    calls = []
    def materialize():
        calls.append("weights")
        pipeline._model = SimpleNamespace(parameters=lambda: iter([parameter]))
    pipeline._load_model = materialize
    monkeypatch.setitem(sys.modules, "yue2", SimpleNamespace(YuE2Pipeline=SimpleNamespace(from_pretrained=lambda *a, **k: pipeline)))
    monkeypatch.setitem(sys.modules, "yue2.protocol", SimpleNamespace(GenerationConfig=lambda **kwargs: SimpleNamespace(**kwargs)))
    monkeypatch.setattr(manager, "native_sampling", lambda config: (None, None))
    monkeypatch.setattr(manager, "_load", lambda config, key: ModelManager._load(manager, config, key))
    manager.acquire(GenerationConfig())
    assert calls == ["weights"] and manager.state()["model_gpu_resident"] is True
    assert manager.state()["vae_gpu_resident"] is False
    manager.begin_use()
    parameter.device = cpu
    assert manager.state()["model_gpu_resident"] is False
    manager.end_use()
    assert manager.state()["loaded"] is True and manager.state()["model_gpu_resident"] is False
