"""Local GPU worker.

Claims one job at a time from the filesystem queue, drives the backend through
its stages, writes artifacts and a manifest, and publishes a heartbeat the API
reads for the System page. It is a separate process from the API on purpose:
blocking GPU work never runs inside an HTTP handler, and the worker can be moved
to another machine that shares the data directory.

Run with:  .venv-yue2/bin/python -m services.yue2_worker.worker
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "core"))

from yue2_studio_core.errors import ErrorCode, StudioError, classify_exception  # noqa: E402
from yue2_studio_core.errors import GUIDANCE  # noqa: E402
from yue2_studio_core.models import GenerationJob, JobStatus, utcnow  # noqa: E402
from yue2_studio_core.queue import FilesystemJobQueue  # noqa: E402
from yue2_studio_core.settings import get_settings  # noqa: E402
from yue2_studio_core.store import Store, write_json_atomic  # noqa: E402

from services.yue2_worker.adapters.base import GenerationContext  # noqa: E402
from services.yue2_worker.engine import artifacts as artifact_writer  # noqa: E402
from services.yue2_worker.jobs.reporter import JobProgressReporter  # noqa: E402
from services.yue2_worker.model_manager.manager import ModelManager  # noqa: E402

logger = logging.getLogger("yue2.worker")

HEARTBEAT_SECONDS = 5.0


def configure_logging() -> None:
    from datetime import datetime, timezone

    class Formatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "severity": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            for key in ("job_id", "generation_id", "stage"):
                value = getattr(record, key, None)
                if value is not None:
                    payload[key] = value
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=False)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(Formatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def build_backend(settings, manager: ModelManager, store=None):
    name = settings.yue2_backend
    if name == "native":
        from services.yue2_worker.adapters.yue2_native import NativeYuE2Backend

        return NativeYuE2Backend(settings, manager, store=store)
    if name == "mock":
        from services.yue2_worker.adapters.mock import MockBackend

        return MockBackend(settings)
    if name == "comfy":
        from services.yue2_worker.adapters.comfy_workflow import ComfyWorkflowBackend

        return ComfyWorkflowBackend(settings)
    raise ValueError(f"unknown backend {name!r}")


def gpu_snapshot(active_index: int | None = None) -> dict:
    """Every device this process can address, plus the one it is using.

    The worker's view is what matters for device selection: CUDA_VISIBLE_DEVICES
    can hide cards from it that the API's NVML query still sees.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return {"available": False, "devices": []}
        current = torch.cuda.current_device() if active_index is None else active_index
        devices = []
        for index in range(torch.cuda.device_count()):
            properties = torch.cuda.get_device_properties(index)
            free, total = torch.cuda.mem_get_info(index)
            devices.append(
                {
                    "index": index,
                    "name": properties.name,
                    "total_bytes": int(total),
                    "free_bytes": int(free),
                    "compute_capability": f"{properties.major}.{properties.minor}",
                    "bf16_supported": bool(properties.major >= 8),
                }
            )
        snapshot = {"available": True, "devices": devices, "active_index": current}
        for device in devices:
            if device["index"] == current:
                snapshot.update(
                    {
                        "index": current,
                        "name": device["name"],
                        "total_bytes": device["total_bytes"],
                        "free_bytes": device["free_bytes"],
                        "compute_capability": device["compute_capability"],
                        "peak_allocated_bytes": int(torch.cuda.max_memory_allocated(current)),
                    }
                )
        return snapshot
    except Exception as exc:
        return {"available": False, "devices": [], "error": str(exc)}


def reset_gpu_peak(index: int | None = None) -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(index)
    except Exception:
        pass


class Worker:
    def __init__(self, *, once: bool = False) -> None:
        self.settings = get_settings()
        self.store = Store(self.settings)
        self.queue = FilesystemJobQueue(self.store, max_concurrent_gpu_jobs=self.settings.max_concurrent_gpu_jobs)
        self.manager = ModelManager(self.settings, store=self.store)
        self.backend = build_backend(self.settings, self.manager, store=self.store)
        self.worker_id = self.settings.worker_id
        self.once = once
        self._stop = asyncio.Event()
        self._current: GenerationJob | None = None

    # -- heartbeat --------------------------------------------------------- #

    @property
    def heartbeat_path(self) -> Path:
        return self.store.root / "worker" / f"{self.worker_id}.json"

    def write_heartbeat(self, state: str) -> None:
        payload = {
            "worker_id": self.worker_id,
            "state": state,
            "backend": self.settings.yue2_backend,
            "updated_at": utcnow().isoformat(),
            "current_generation_id": self._current.id if self._current else None,
            "max_concurrent_gpu_jobs": self.settings.max_concurrent_gpu_jobs,
            "model": self.manager.state(),
            "runtime": self.manager.runtime_versions(),
            "gpu": gpu_snapshot(self.manager.device_index),
            "pid": os.getpid(),
        }
        write_json_atomic(self.heartbeat_path, payload)

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            state = "busy" if self._current else "idle"
            try:
                self.write_heartbeat(state)
                if self._current is None:
                    self.manager.maybe_unload_idle()
            except Exception:
                logger.exception("heartbeat failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                continue

    # -- cancellation ------------------------------------------------------ #

    def _cancel_watcher(self, job_id: str, event: threading.Event, done: threading.Event) -> None:
        """Watch the job document for a cancellation request.

        Cancellation is cooperative: this only raises the flag the backend
        stages check at their next safe boundary.
        """
        interval = self.settings.cancel_poll_interval_seconds
        while not done.wait(interval):
            if self.store.is_cancel_requested(job_id):
                event.set()
                return

    # -- job execution ----------------------------------------------------- #

    async def run_job(self, job: GenerationJob) -> None:
        self._current = job
        reporter = JobProgressReporter(self.store, job)
        cancel_event = threading.Event()
        done = threading.Event()
        watcher = threading.Thread(
            target=self._cancel_watcher, args=(job.id, cancel_event, done), daemon=True, name="cancel-watch"
        )
        watcher.start()
        directory = self.store.prepare_generation_dir(job.project_id, job.id)
        context = GenerationContext(
            job_id=job.id, config=job.config, reporter=reporter, cancel_event=cancel_event
        )
        started = time.perf_counter()
        reset_gpu_peak(self.manager.device_index)
        try:
            warnings = await self.backend.validate_config(job.config)
            for message in warnings:
                reporter.note(message, severity="WARNING")

            await self.backend.prepare(job.config, context)
            load_seconds = time.perf_counter() - started

            plan = await self.backend.generate_plan(context)
            if cancel_event.is_set():
                raise StudioError(ErrorCode.CANCELLED, "Cancelled after planning.", stage="planning")

            tokens = await self.backend.generate_audio(context, plan)
            if cancel_event.is_set():
                raise StudioError(ErrorCode.CANCELLED, "Cancelled after generation.", stage="semantic")

            audio = await self.backend.decode_audio(context, tokens)
            result = await self.backend.finalise(context, plan, tokens, audio)

            reporter.begin(JobStatus.POST_PROCESSING, "post_processing", "Saving artifacts")
            post_started = time.perf_counter()
            job.artifacts = []
            job.artifacts += artifact_writer.write_audio(
                self.store, directory, audio.audio, audio.sample_rate, job.config.output.format.value
            )
            score, score_artifacts = artifact_writer.write_score(self.store, job, plan.abc)
            job.artifacts += score_artifacts
            job.artifacts += artifact_writer.write_intermediates(
                self.store,
                directory,
                latents=tokens.latents,
                semantic_tokens=result.semantic_tokens,
            )
            job.artifacts += artifact_writer.write_configs(self.store, directory, job, result.effective_config)

            audio_artifact = job.audio_artifact()
            job.request_identity = result.request_identity
            job.truncated = {"abc": plan.truncated, "semantic": tokens.truncated}
            job.timing.model_load_seconds = round(load_seconds, 3)
            job.timing.planning_seconds = round(float(plan.timing.get("wall_seconds", 0.0)), 3)
            job.timing.semantic_seconds = round(float(tokens.timing.get("semantic_seconds", 0.0)), 3)
            job.timing.synthesis_seconds = round(float(tokens.timing.get("synthesis_seconds", 0.0)), 3)
            job.timing.decode_seconds = round(float(audio.timing.get("decode_seconds", 0.0)), 3)
            job.timing.output_seconds = audio_artifact.duration_seconds if audio_artifact else None
            snapshot = gpu_snapshot(self.manager.device_index)
            job.timing.gpu_peak_bytes = snapshot.get("peak_allocated_bytes")

            if plan.truncated:
                reporter.note("The symbolic plan hit its token limit and was truncated.", severity="WARNING")
            if tokens.truncated:
                reporter.note("Audio generation hit its token limit; the song may end abruptly.", severity="WARNING")

            # Stamp the completion time and the full elapsed time before the
            # manifest is built, so the manifest is a complete record.
            job.finished_at = utcnow()
            job.timing.post_processing_seconds = round(time.perf_counter() - post_started, 3)
            job.timing.total_seconds = round(time.perf_counter() - started, 3)
            manifest_artifact = artifact_writer.write_manifest(
                self.store,
                directory,
                job,
                runtime=result.runtime,
                weights=result.weights,
                effective_config=result.effective_config,
                hardware=snapshot,
            )
            job.artifacts.append(manifest_artifact)
            self.store.transition(job, JobStatus.COMPLETED, strict=False)
            self.store.append_log(job, "INFO", "completed", "Generation complete.")
            logger.info("generation complete", extra={"generation_id": job.id})

            project = self.store.get_project(job.project_id)
            project.current_generation_id = job.id
            self.store.save_project(project)

        except BaseException as exc:  # noqa: BLE001 - every failure is recorded
            code = exc.code if isinstance(exc, StudioError) else classify_exception(exc)
            stage = exc.stage if isinstance(exc, StudioError) else job.progress.stage
            message = exc.message if isinstance(exc, StudioError) else f"{type(exc).__name__}: {exc}"
            cancelled = code is ErrorCode.CANCELLED or cancel_event.is_set()
            job.error_code = ErrorCode.CANCELLED.value if cancelled else code.value
            job.error_message = message
            job.error_guidance = GUIDANCE.get(ErrorCode.CANCELLED if cancelled else code, "")
            job.timing.total_seconds = round(time.perf_counter() - started, 3)
            artifact_writer.write_failure(
                directory,
                {
                    "status": "cancelled" if cancelled else "failed",
                    "error_code": job.error_code,
                    "error_message": message,
                    "stage": stage,
                    "requested_config": json.loads(job.config.model_dump_json()),
                },
            )
            self.store.append_log(job, "ERROR", stage or "unknown", message)
            self.store.transition(job, JobStatus.CANCELLED if cancelled else JobStatus.FAILED, strict=False)
            logger.error("generation failed", extra={"generation_id": job.id, "stage": stage}, exc_info=not cancelled)
        finally:
            done.set()
            reporter.flush()
            self._current = None

    # -- main loop --------------------------------------------------------- #

    async def run(self) -> None:
        logger.info("worker %s starting on backend %s", self.worker_id, self.settings.yue2_backend)
        self.write_heartbeat("starting")
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            while not self._stop.is_set():
                job = await asyncio.to_thread(
                    self.queue.claim, self.worker_id
                )
                if job is None:
                    if self.once:
                        break
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self.settings.worker_poll_interval_seconds)
                    except asyncio.TimeoutError:
                        pass
                    continue
                logger.info("claimed generation", extra={"generation_id": job.id})
                await self.run_job(job)
                if self.once:
                    break
        finally:
            self._stop.set()
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            await self.backend.shutdown()
            self.write_heartbeat("stopped")
            logger.info("worker stopped")

    def request_stop(self) -> None:
        self._stop.set()


async def main_async(once: bool) -> int:
    worker = Worker(once=once)
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, worker.request_stop)
        except NotImplementedError:
            pass
    await worker.run()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="YuE2 Music Studio GPU worker")
    parser.add_argument("--once", action="store_true", help="process a single job and exit")
    args = parser.parse_args()
    configure_logging()
    return asyncio.run(main_async(args.once))


if __name__ == "__main__":
    raise SystemExit(main())
