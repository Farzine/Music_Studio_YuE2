"""Serial device transitions using fake pipelines and CUDA counters, no GPU."""
import asyncio
import contextlib
import sys
import threading
from types import SimpleNamespace

import pytest

from services.yue2_worker.model_manager.manager import ModelManager
from yue2_studio_core.errors import ConflictError, ErrorCode, StudioError
from yue2_studio_core.model_files import model_file_leases
from yue2_studio_core.models import GenerationConfig


def switch(worker, index=1):
    queued = worker.commands.enqueue(worker_id=worker.worker_id, worker_session=worker.session_id,
                                     operation="select_device", device_index=index)
    asyncio.run(worker.run_command(worker.commands.claim(worker.worker_id, worker.session_id)))
    return worker.commands.get(queued.id)


def test_switch_releases_before_target_load_and_pins_rollback_files(runtime_worker, monkeypatch):
    worker, stages, calls = runtime_worker, [], []
    manager = worker.manager
    config = GenerationConfig()
    config.model.compute_backend = "torch-eager"
    manager.acquire(config)
    model, vae = manager._key.model, manager._key.vae
    manager._pipeline.close = lambda: calls.append("close0")
    original_load = manager._load
    def load(config, key):
        calls.append(f"load{key.device_index}")
        assert not manager.loaded
        assert manager.device_index == 0  # commit after successful materialization
        assert (key.model, key.vae, key.backend) == (model, vae, "torch-eager")
        for reference in (model, vae):
            with pytest.raises(ConflictError):
                with model_file_leases(worker.store, [reference], shared=False, blocking=False):
                    pass
        return original_load(config, key)
    monkeypatch.setattr(manager, "_load", load)
    original_advance = worker.commands.advance
    def advance(command, stage, message):
        stages.append(stage)
        original_advance(command, stage, message)
    monkeypatch.setattr(worker.commands, "advance", advance)
    result = switch(worker)
    assert result.status == "succeeded" and result.progress["stage"] == "ready"
    assert calls == ["close0", "load1"]
    assert stages == ["unloading", "released", "loading", "ready"]
    assert manager.device_index == 1 and result.result["device_index"] == 1


@pytest.mark.parametrize("failure", ["load", "memory", "commit"])
def test_failed_target_restores_previous_model_and_selection(runtime_worker, monkeypatch, failure):
    manager = runtime_worker.manager
    manager.acquire(GenerationConfig())
    original_load, original_write = manager._load, manager._store.write_runtime_settings
    calls = []
    def load(config, key):
        calls.append(key.device_index)
        if key.device_index == 1 and failure in {"load", "memory"}:
            code = ErrorCode.CUDA_OOM if failure == "memory" else ErrorCode.MODEL_LOAD_FAILED
            raise StudioError(code, "target fixture failure")
        return original_load(config, key)
    def write(values):
        if values["device_index"] == 1:
            raise OSError("settings write failed")
        return original_write(values)
    monkeypatch.setattr(manager, "_load", load)
    if failure == "commit":
        monkeypatch.setattr(manager._store, "write_runtime_settings", write)
    result = switch(runtime_worker)
    assert result.status == "failed" and result.error["details"]["rollback_succeeded"]
    assert result.progress["stage"] == "restored"
    assert manager.device_index == 0 and manager.state()["device_index"] == 0 and manager.loaded
    assert calls == [1, 0]


@pytest.mark.parametrize("failure", ["unavailable", "unload", "in_use"])
def test_refused_switch_never_loads_target(runtime_worker, monkeypatch, failure):
    manager = runtime_worker.manager
    manager.acquire(GenerationConfig())
    def fail(*args):
        raise RuntimeError("fixture resource failure")
    if failure == "unavailable":
        def unavailable(index):
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, "GPU unavailable")
        monkeypatch.setattr(manager, "_validate_device", unavailable)
    elif failure == "unload":
        manager._pipeline.close = fail
    else:
        manager.begin_use()
    monkeypatch.setattr(manager, "_load", lambda *args: pytest.fail("Must not load target"))
    result = switch(runtime_worker)
    assert result.status == "failed" and manager.device_index == 0
    assert manager.state()["device_index"] == 0 and manager.loaded
    assert result.result["lifecycle"] == ("UNLOAD_FAILED" if failure == "unload" else "IN_USE" if failure == "in_use" else "LOADED")


def test_uncertain_target_cleanup_blocks_rollback_allocation(runtime_worker, monkeypatch):
    manager = runtime_worker.manager
    manager.acquire(GenerationConfig())
    original_load = manager._load
    calls = []
    def load(config, key):
        calls.append(key.device_index)
        original_load(config, key)
        def fail():
            raise RuntimeError("target cannot close")
        manager._pipeline.close = fail
        raise StudioError(ErrorCode.MODEL_LOAD_FAILED, "partial target load")
    monkeypatch.setattr(manager, "_load", load)
    result = switch(runtime_worker)
    assert result.status == "failed" and not result.error["details"]["rollback_succeeded"]
    assert result.result["lifecycle"] == "UNLOAD_FAILED" and calls == [1]
    assert manager.device_index == 0
    with pytest.raises(ConflictError):
        manager.acquire(GenerationConfig())


def test_rollback_load_failure_leaves_old_selection_and_clean_failed_state(runtime_worker, monkeypatch):
    manager = runtime_worker.manager
    manager.acquire(GenerationConfig())
    calls = []
    def fail(config, key):
        calls.append(key.device_index)
        raise StudioError(ErrorCode.CUDA_OOM, "not enough memory on either device")
    monkeypatch.setattr(manager, "_load", fail)
    result = switch(runtime_worker)
    assert calls == [1, 0] and result.status == "failed"
    assert not result.error["details"]["rollback_succeeded"]
    assert manager.device_index == 0 and not manager.loaded
    assert result.result["lifecycle"] == "LOAD_FAILED"


def test_idle_and_same_device_switch_do_not_invent_model_loading(runtime_worker, monkeypatch):
    monkeypatch.setattr(runtime_worker.manager, "_load", lambda *args: pytest.fail("No model to reload"))
    result = switch(runtime_worker)
    assert result.status == "succeeded" and result.result["lifecycle"] == "UNLOADED"
    assert runtime_worker.store.device_index() == 1
    assert switch(runtime_worker).status == "succeeded"


def test_vllm_switch_prepares_device_wrapper_without_claiming_preloaded_weights(runtime_worker, monkeypatch):
    manager = runtime_worker.manager
    original = manager._load
    def load(config, key):
        pipeline, loaded = original(config, key)
        pipeline._model = pipeline._vae = pipeline._vllm_worker = None
        return pipeline, loaded
    monkeypatch.setattr(manager, "_load", load)
    config = GenerationConfig()
    config.model.compute_backend = "vllm"
    manager.acquire(config)
    result = switch(runtime_worker)
    assert result.status == "succeeded" and result.result["device_index"] == 1
    assert result.result["pipeline_ready"] and not result.result["loaded"]
    assert "during the next generation" in result.progress["message"]


@pytest.mark.parametrize("retained", [0, 128])
def test_cuda_release_synchronizes_and_checks_worker_allocator(monkeypatch, retained):
    calls = []
    cuda = SimpleNamespace(device=lambda index: contextlib.nullcontext(),
        synchronize=lambda index: calls.append("synchronize"), empty_cache=lambda: calls.append("empty"),
        ipc_collect=lambda: calls.append("ipc"), memory_allocated=lambda index: retained,
        memory_reserved=lambda index: retained)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))
    if retained:
        with pytest.raises(RuntimeError, match="retains 128"):
            ModelManager._clear_cuda(0)
    else:
        ModelManager._clear_cuda(0)
    assert calls == ["synchronize", "empty", "ipc"]


def test_pipeline_close_must_drop_model_and_wait_for_child(runtime_manager):
    runtime_manager.acquire(GenerationConfig())
    runtime_manager._pipeline._model = object()
    with pytest.raises(StudioError, match="retains model/VAE"):
        runtime_manager.release()
    runtime_manager._pipeline._model = None
    runtime_manager._pipeline._vllm_worker = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
    with pytest.raises(StudioError, match="child is still running"):
        runtime_manager.release()
    runtime_manager._pipeline._vllm_worker = None
    runtime_manager.release()


def test_native_loading_and_cover_transcription_use_captured_job_device(runtime_manager, monkeypatch):
    from services.yue2_worker.adapters.base import GenerationContext
    from services.yue2_worker.adapters.yue2_native import NativeYuE2Backend
    from yue2_studio_core.models import GenerationMode
    from yue2_studio_core.ids import new_id
    manager = runtime_manager
    adapter = NativeYuE2Backend(manager.settings, manager, manager._store)
    config = GenerationConfig()
    config.prompt.mode = GenerationMode.COVER
    config.prompt.reference_upload_id = "upload_fixture"
    manager._store.write_runtime_settings({"device_index": 1})
    reporter = SimpleNamespace(begin=lambda *a, **k: None, note=lambda *a, **k: None, update=lambda *a, **k: None)
    context = GenerationContext(new_id("gen"), config, reporter, threading.Event(), device_index=0)
    monkeypatch.setattr(adapter.store, "get_upload", lambda id: SimpleNamespace(path="ref.wav"))
    monkeypatch.setattr(adapter.store, "get_job", lambda id: SimpleNamespace(project_id=new_id("prj")))
    indices = []
    def transcribe(*args, **kwargs):
        indices.append(kwargs["device_index"])
        return SimpleNamespace(abc="fixture score", warnings=[], duration_seconds=None, elapsed_seconds=None)
    monkeypatch.setattr(adapter.transcriber, "transcribe", transcribe)
    original = manager._load
    def load(config, key):
        result = original(config, key)
        result[0].effective_config = lambda *a: {}
        return result
    monkeypatch.setattr(manager, "_load", load)
    monkeypatch.setattr(manager, "native_sampling", lambda config: (None, None))
    monkeypatch.setitem(sys.modules, "yue2.protocol", SimpleNamespace(SongRequest=lambda **kwargs: SimpleNamespace(**kwargs)))
    asyncio.run(adapter.prepare(config, context))
    assert indices == [0] and manager.state()["device_index"] == 0
    assert manager.device_index == 1  # settings edits cannot move a running job
    adapter.end_job()


@pytest.mark.parametrize("visible, index, expected", [("3,1", 1, "1"), ("GPU-a,GPU-b", 0, "GPU-a"), (None, 1, "1")])
def test_transcription_child_preserves_parent_cuda_index_mapping(runtime_manager, monkeypatch, tmp_path, visible, index, expected):
    from services.yue2_worker.adapters import transcription
    transcriber = transcription.SheetSage2Transcriber(runtime_manager.settings)
    monkeypatch.setattr(transcriber, "available", lambda: (True, None))
    if visible is None:
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    else:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visible)
    class LaunchObserved(Exception):
        pass
    def launch(command, **kwargs):
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == expected
        raise LaunchObserved
    monkeypatch.setattr(transcription.subprocess, "Popen", launch)
    with pytest.raises(LaunchObserved):
        transcriber.transcribe(tmp_path / "audio.wav", tmp_path / "score", device_index=index)
