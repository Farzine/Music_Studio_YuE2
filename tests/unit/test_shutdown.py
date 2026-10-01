"""Shutdown and cancellation with fake models and real CPU-only fixture children."""
import asyncio
import json
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from yue2_studio_core.errors import ConflictError, ErrorCode, StudioError
from yue2_studio_core.ids import new_id
from yue2_studio_core.models import GenerationConfig, GenerationJob, JobStatus
from yue2_studio_core.store import write_json_atomic


def job(worker, *, status=JobStatus.QUEUED):
    project = worker.store.create_project(title="shutdown test")
    return worker.store.save_job(GenerationJob(id=new_id("gen"), project_id=project.id,
                         config=GenerationConfig(), status=status,
                         worker_id=worker.worker_id if status.is_active else None))


def test_shutdown_fails_pending_control_and_releases_model(runtime_worker):
    worker = runtime_worker
    worker.manager.acquire(GenerationConfig())
    pending = worker.commands.enqueue(worker_id=worker.worker_id, worker_session=worker.session_id,
                 operation="load", registry_id="model_fixture", reference=worker.settings.model_reference, device_index=0)
    worker.request_stop()
    request = worker.commands.request_shutdown(worker.worker_id, worker.session_id)
    assert worker.commands.claim(worker.worker_id, worker.session_id) is None
    assert request.id == worker.commands.request_shutdown(worker.worker_id, worker.session_id).id
    with pytest.raises(ConflictError, match="stopping"):
        worker.commands.enqueue(worker_id=worker.worker_id, worker_session=worker.session_id,
                               operation="select_device", device_index=1)
    asyncio.run(worker.run())
    assert not worker.manager.loaded
    assert worker.commands.get(pending.id).error["error_code"] == "CANCELLED"
    assert worker.commands.get(request.id).status == "succeeded"
    assert worker.commands.request_shutdown(worker.worker_id, worker.session_id).id == request.id
    heartbeat = json.loads(worker.heartbeat_path.read_text())
    assert heartbeat["state"] == "stopped" and not heartbeat["accepting_work"]
    assert heartbeat["shutdown"]["status"] == "completed"


def test_every_cleanup_step_and_stopped_state_survive_failures(runtime_worker, monkeypatch):
    worker = runtime_worker
    worker.manager.acquire(GenerationConfig())
    calls = []
    def fail_close():
        calls.append("model")
        raise RuntimeError("fixture close failed")
    def fail_refs():
        calls.append("references")
        raise RuntimeError("fixture references failed")
    async def fail_backend():
        calls.append("backend")
        raise RuntimeError("fixture backend failed")
    worker.manager._pipeline.close = fail_close
    monkeypatch.setattr(worker.backend, "end_job", fail_refs, raising=False)
    monkeypatch.setattr(worker.backend, "shutdown", fail_backend)
    worker.request_stop()
    with pytest.raises(StudioError, match="shutdown cleanup failed"):
        asyncio.run(worker.run())
    assert calls == ["references", "backend", "model"]
    heartbeat = json.loads(worker.heartbeat_path.read_text())
    assert heartbeat["state"] == "stopped" and heartbeat["shutdown"]["status"] == "failed"
    assert heartbeat["model"]["lifecycle"] == "UNLOAD_FAILED"
    assert {e["stage"] for e in heartbeat["shutdown"]["errors"]} == {"adapter_references", "backend", "model_resources"}
    assert next(c for c in worker.commands.list() if c.operation == "shutdown").status == "failed"


@pytest.mark.parametrize("cancel_task", [False, True])
def test_stop_cancels_active_job_and_preserves_waiting_jobs(runtime_worker, monkeypatch, cancel_task):
    worker = runtime_worker
    worker.manager.acquire(GenerationConfig())
    first, waiting = job(worker), job(worker)
    async def run():
        entered = asyncio.Event()
        async def block(context):
            entered.set()
            while not context.cancelled():
                await asyncio.sleep(0.01)
            raise StudioError(ErrorCode.CANCELLED, "fixture cancelled")
        monkeypatch.setattr(worker.backend, "generate_plan", block)
        task = asyncio.create_task(worker.run())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel() if cancel_task else worker.request_stop()
        await asyncio.wait_for(task, 5)
    asyncio.run(run())
    assert worker.store.get_job(first.id).status is JobStatus.CANCELLED
    assert worker.store.get_job(waiting.id).status is JobStatus.QUEUED
    assert not worker.manager.loaded and worker._current is None


def test_task_cancellation_settles_blocking_load_before_cleanup(runtime_worker, monkeypatch):
    worker = runtime_worker
    entered, finish = threading.Event(), threading.Event()
    original = worker.manager._load
    calls = []
    def load(config, key):
        entered.set()
        assert finish.wait(3)
        result = original(config, key)
        result[0].close = lambda: calls.append("close")
        calls.append("loaded")
        return result
    monkeypatch.setattr(worker.manager, "_load", load)
    config = GenerationConfig()
    config.model.checkpoint = worker.settings.model_reference
    pending = worker.commands.enqueue(worker_id=worker.worker_id, worker_session=worker.session_id,
          operation="load", registry_id="model_fixture", reference=worker.settings.model_reference, config=config, device_index=0)
    async def run():
        task = asyncio.create_task(worker.run_command(worker.commands.claim(worker.worker_id, worker.session_id)))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0.02)
        task.cancel()  # repeated cancellation must not detach the CUDA thread
        assert not task.done() and calls == []
        finish.set()
        await asyncio.wait_for(task, 3)
        await worker._shutdown(None)
    asyncio.run(run())
    assert calls == ["loaded", "close"]
    assert worker.commands.get(pending.id).error["error_code"] == "CANCELLED"
    assert not worker.manager.loaded


def test_restart_marks_abandoned_generation_failed_without_replay(runtime_worker):
    worker = runtime_worker
    interrupted = job(worker, status=JobStatus.GENERATING)
    worker.once = True
    asyncio.run(worker.run())
    saved = worker.store.get_job(interrupted.id)
    assert saved.status is JobStatus.FAILED and saved.finished_at is not None
    assert "not replayed" in saved.error_message


def test_reporter_failure_does_not_skip_end_job_or_runtime_state_reset(runtime_worker, monkeypatch):
    from services.yue2_worker.jobs.reporter import JobProgressReporter
    worker = runtime_worker
    worker.manager.acquire(GenerationConfig())
    calls = []
    async def cancel(context):
        raise StudioError(ErrorCode.CANCELLED, "fixture cancelled")
    def fail_flush(self):
        raise OSError("fixture progress write failed")
    monkeypatch.setattr(worker.backend, "generate_plan", cancel)
    monkeypatch.setattr(worker.backend, "end_job", lambda: calls.append("end"), raising=False)
    monkeypatch.setattr(JobProgressReporter, "flush", fail_flush)
    with pytest.raises(OSError, match="progress write"):
        asyncio.run(worker.run_job(job(worker)))
    assert calls == ["end"] and worker._current is None
    assert worker.manager.state()["lifecycle"] == "IDLE"


def test_sigterm_handler_runs_graceful_cleanup(runtime_worker, monkeypatch):
    from services.yue2_worker import worker as module
    runtime_worker.manager.acquire(GenerationConfig())
    monkeypatch.setattr(module, "Worker", lambda once: runtime_worker)
    async def run():
        callbacks = {}
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "add_signal_handler", lambda signum, callback: callbacks.setdefault(signum, callback))
        loop.call_soon(lambda: callbacks[signal.SIGTERM]())
        assert await module.main_async(False) == 0
        assert set(callbacks) == {signal.SIGINT, signal.SIGTERM}
    asyncio.run(run())
    assert not runtime_worker.manager.loaded


@pytest.mark.parametrize("reason", ["cancel", "timeout", "callback", "stderr"])
def test_transcription_always_reaps_child_and_drains_pipes(runtime_manager, monkeypatch, tmp_path, reason):
    from services.yue2_worker.adapters import transcription
    transcriber = transcription.SheetSage2Transcriber(runtime_manager.settings)
    monkeypatch.setattr(transcriber, "available", lambda: (True, None))
    if reason == "timeout":
        transcriber.settings.sheetsage2_timeout_seconds = -1
    processes = []
    original = subprocess.Popen
    output = tmp_path / "score"
    script = "import time; print('Window 1/2', flush=True); time.sleep(30)"
    if reason == "stderr":
        report = str(output / "transcription.json")
        script = f"import sys,json; sys.stderr.write('x'*100000); open({report!r},'w').write(json.dumps({{'status':'complete','abc':'X:1'}}))"
    def spawn(command, **kwargs):
        process = original([sys.executable, "-c", script], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(transcription.subprocess, "Popen", spawn)
    def cancelled():
        return reason == "cancel" and bool(processes)
    def progress(*args):
        if reason == "callback":
            raise RuntimeError("fixture callback failed")
    if reason == "stderr":
        assert transcriber.transcribe(tmp_path / "audio.wav", output, device_index=0, on_progress=progress).abc == "X:1"
    else:
        with pytest.raises((StudioError, RuntimeError)):
            transcriber.transcribe(tmp_path / "audio.wav", output, device_index=0, cancelled=cancelled, on_progress=progress)
    assert len(processes) == 1 and processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed


@pytest.mark.parametrize("cancel_task", [False, True])
def test_audiocpp_shutdown_reaps_process_before_clearing_residency(runtime_manager, tmp_path, cancel_task):
    from services.yue2_worker.adapters.audiocpp import AudioCppBackend
    from services.yue2_worker.adapters.base import GenerationContext
    manager = runtime_manager
    model = tmp_path / "gguf"
    model.mkdir()
    write_json_atomic(model / "studio-model.json", {"filename": "fixture.gguf"})
    cli = tmp_path / "fake_cli"
    cli.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    cli.chmod(0o755)
    manager.settings.audiocpp_cli_path = str(cli)
    config = GenerationConfig()
    config.model.checkpoint = str(model)
    project = manager._store.create_project(title="CLI shutdown")
    generation = manager._store.save_job(GenerationJob(id=new_id("gen"), project_id=project.id, config=config))
    context = GenerationContext(generation.id, config, SimpleNamespace(begin=lambda *a, **k: None), threading.Event())
    backend = AudioCppBackend(manager.settings, manager._store)
    backend.manager = manager
    async def run():
        task = asyncio.create_task(backend.generate_plan(context))
        for _ in range(200):
            if manager.state()["process_id"]:
                break
            await asyncio.sleep(0.01)
        process = backend._process
        assert process is not None and manager.state()["lifecycle"] == "IN_USE"
        task.cancel() if cancel_task else context.cancel_event.set()
        with pytest.raises((StudioError, asyncio.CancelledError)):
            await asyncio.wait_for(task, 4)
        assert process.returncode is not None and backend._process is None
        assert manager.state()["lifecycle"] == "UNLOADED"
        await backend.shutdown()  # idempotent after cancellation
    asyncio.run(run())
