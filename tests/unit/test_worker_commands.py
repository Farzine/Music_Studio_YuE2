import asyncio

import pytest

from yue2_studio_core.errors import ConflictError, ErrorCode, StudioError
from yue2_studio_core.model_registry import ModelRegistry
from yue2_studio_core.models import GenerationConfig
from yue2_studio_core.store import file_lock


def command(worker, operation="load", reference=None, config=None):
    reference = reference or worker.settings.model_reference
    return worker.commands.enqueue(worker_id=worker.worker_id, worker_session=worker.session_id,
                                   operation=operation, registry_id="model_fixture", reference=reference,
                                   config=config or GenerationConfig(), device_index=1)


def execute(worker, queued):
    claimed = worker.commands.claim(worker.worker_id, worker.session_id)
    asyncio.run(worker.run_command(claimed))
    return worker.commands.get(queued.id)


def test_worker_load_and_unload_acknowledges_authoritative_state(runtime_worker, monkeypatch):
    worker = runtime_worker
    from services.yue2_worker import worker as module
    observed = []
    monkeypatch.setattr(module, "gpu_snapshot", lambda index: observed.append(index) or {"devices": []})
    original = worker.manager._load
    def load(config, key):
        worker.write_heartbeat("busy")
        assert worker.manager.state()["lifecycle"] == "LOADING"
        assert observed[-1] == key.device_index  # targeted GPU, before any tensors exist
        return original(config, key)
    monkeypatch.setattr(worker.manager, "_load", load)
    config = GenerationConfig()
    config.model.checkpoint = worker.settings.model_reference
    loaded = execute(worker, command(worker, config=config))
    assert loaded.status == "succeeded"
    assert loaded.result["lifecycle"] == "LOADED" and loaded.result["device_index"] == 1
    unloaded = execute(worker, command(worker, "unload"))
    assert unloaded.status == "succeeded" and unloaded.result["lifecycle"] == "UNLOADED"
    assert worker._command is None


def test_unload_does_not_release_a_different_resident_model(runtime_worker):
    worker = runtime_worker
    worker.manager.acquire(GenerationConfig())
    result = execute(worker, command(worker, "unload", reference="/another/model"))
    assert result.status == "failed" and result.error["error_code"] == "CONFLICT"
    assert worker.manager.loaded


def test_worker_refuses_failed_validation_via_direct_path_command(runtime_worker):
    worker = runtime_worker
    registry = ModelRegistry(worker.settings, worker.store)
    entry = registry.register(worker.settings.model_reference)
    from yue2_studio_core.model_validator import validate_installation
    (worker.settings.models_path / "native" / "model.safetensors").write_bytes(b"corrupt")
    registry.save_validation(validate_installation(entry))
    config = GenerationConfig()
    config.model.checkpoint = worker.settings.model_reference
    result = execute(worker, command(worker, config=config))
    assert result.status == "failed" and result.error["error_code"] == "INVALID_CONFIG"
    assert not worker.manager.loaded


def test_worker_survives_load_failure_and_reports_it(runtime_worker, monkeypatch):
    worker = runtime_worker
    def fail(*args):
        raise StudioError(ErrorCode.MODEL_LOAD_FAILED, "mock failure")
    monkeypatch.setattr(worker.manager, "_load", fail)
    config = GenerationConfig()
    config.model.checkpoint = worker.settings.model_reference
    result = execute(worker, command(worker, config=config))
    assert result.status == "failed" and result.result["lifecycle"] == "LOAD_FAILED"
    assert result.error["error_code"] == "MODEL_LOAD_FAILED" and worker._command is None


def test_exclusive_worker_invocation_preserves_other_session(runtime_worker):
    import hashlib
    worker = runtime_worker
    path = worker.store.root / "worker" / f".{hashlib.sha256(worker.worker_id.encode()).hexdigest()}.process.lock"
    queued = command(worker)
    with file_lock(path):
        with pytest.raises(ConflictError):
            asyncio.run(worker.run())
    assert worker.commands.get(queued.id).status == "queued"


def test_unload_waits_for_active_inference_and_runs_before_next_job(runtime_worker, monkeypatch):
    from yue2_studio_core.ids import new_id
    from yue2_studio_core.models import GenerationJob, JobStatus
    worker = runtime_worker
    worker.manager.acquire(GenerationConfig())
    project = worker.store.create_project(title="command ordering")
    first = worker.store.save_job(GenerationJob(id=new_id("gen"), project_id=project.id, config=GenerationConfig()))
    worker.store.save_job(GenerationJob(id=new_id("gen"), project_id=project.id, config=GenerationConfig()))

    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()
        original = worker.backend.generate_plan
        calls = []
        async def block(context):
            calls.append(context.job_id)
            entered.set()
            await finish.wait()
            return await original(context)
        monkeypatch.setattr(worker.backend, "generate_plan", block)
        original_command = worker.run_command
        async def stop_after_command(claimed):
            await original_command(claimed)
            worker.request_stop()
        monkeypatch.setattr(worker, "run_command", stop_after_command)
        task = asyncio.create_task(worker.run())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert worker.manager.state()["lifecycle"] == "IN_USE"
            queued = command(worker, "unload")
            assert worker.commands.get(queued.id).status == "queued" and worker.manager.loaded
            finish.set()
            await asyncio.wait_for(task, 10)
            assert worker.commands.get(queued.id).status == "succeeded"
            assert worker.store.get_job(first.id).status is JobStatus.COMPLETED
            assert len(calls) == 1  # second queued job did not bypass control
        finally:
            finish.set()
            worker.request_stop()
            if not task.done():
                await task
    asyncio.run(run())
