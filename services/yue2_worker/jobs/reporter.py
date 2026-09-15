"""Progress reporting from the worker into the job document.

Only real backend stages are reported. A percentage is computed only when the
stage has a genuine target; a token limit is a ceiling, not a target, so token
stages report counts and rate with ``percent = None``.
"""
from __future__ import annotations

import threading
import time

from yue2_studio_core.models import GenerationJob, JobStatus, ProgressState, utcnow
from yue2_studio_core.store import Store

MIN_WRITE_INTERVAL = 0.25


class JobProgressReporter:
    def __init__(self, store: Store, job: GenerationJob) -> None:
        self.store = store
        self.job = job
        self._lock = threading.RLock()
        self._last_write = 0.0
        self._stage_started = time.monotonic()

    # -- ProgressReporter protocol ---------------------------------------- #

    def begin(
        self,
        status: JobStatus,
        stage: str,
        label: str,
        *,
        total: int | None = None,
        unit: str | None = None,
    ) -> None:
        with self._lock:
            self._stage_started = time.monotonic()
            if self.job.status is not status and self.job.status is not JobStatus.CANCEL_REQUESTED:
                self.store.transition(self.job, status, strict=False)
            self.job.progress = ProgressState(
                stage=stage,
                label=label,
                completed=0,
                total=total,
                unit=unit,
                percent=0.0 if total else None,
            )
            self.store.append_log(self.job, "INFO", stage, label)
            self._write(force=True)

    def update(self, completed: int, *, total: int | None = None) -> None:
        with self._lock:
            progress = self.job.progress
            progress.completed = completed
            if total is not None:
                progress.total = total
            elapsed = max(time.monotonic() - self._stage_started, 1e-6)
            progress.rate_per_second = round(completed / elapsed, 2)
            progress.percent = (
                round(min(100.0, 100.0 * completed / progress.total), 2) if progress.total else None
            )
            progress.updated_at = utcnow()
            self._write()

    def note(self, message: str, *, severity: str = "INFO") -> None:
        with self._lock:
            self.store.append_log(self.job, severity, self.job.progress.stage, message)
            if severity in {"WARNING", "ERROR"}:
                self.job.warnings.append(message)
                self._write(force=True)

    # -- persistence ------------------------------------------------------- #

    def _write(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_write >= MIN_WRITE_INTERVAL:
            self._last_write = now
            self.store.save_job(self.job)

    def flush(self) -> None:
        with self._lock:
            self._write(force=True)
