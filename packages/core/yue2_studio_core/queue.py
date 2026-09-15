"""Queue abstraction.

The local build uses the filesystem store directly: the API writes a job
document and the worker claims it under an advisory lock. Swapping in Redis/RQ,
Celery or Dramatiq later means implementing :class:`JobQueue` elsewhere; no
caller depends on the filesystem details.
"""
from __future__ import annotations

from typing import Protocol

from .models import GenerationJob, JobStatus
from .store import Store


class JobQueue(Protocol):
    def enqueue(self, job: GenerationJob) -> GenerationJob: ...

    def claim(self, worker_id: str) -> GenerationJob | None: ...

    def heartbeat(self, job: GenerationJob) -> GenerationJob: ...

    def request_cancel(self, job_id: str) -> GenerationJob: ...

    def pending(self) -> list[GenerationJob]: ...

    def depth(self) -> int: ...


class FilesystemJobQueue:
    """Single-machine queue backed by ``DATA_DIR/jobs``."""

    def __init__(self, store: Store, *, max_concurrent_gpu_jobs: int = 1) -> None:
        self.store = store
        self.max_concurrent_gpu_jobs = max_concurrent_gpu_jobs

    def enqueue(self, job: GenerationJob) -> GenerationJob:
        job.status = JobStatus.QUEUED
        job.queue_position = len(self.pending()) + 1
        return self.store.save_job(job)

    def claim(self, worker_id: str) -> GenerationJob | None:
        return self.store.claim_next_job(worker_id, max_concurrent=self.max_concurrent_gpu_jobs)

    def heartbeat(self, job: GenerationJob) -> GenerationJob:
        return self.store.save_job(job)

    def request_cancel(self, job_id: str) -> GenerationJob:
        with self.store.queue_lock():
            job = self.store.get_job(job_id)
            if job.status.is_terminal:
                return job
            self.store.mark_cancel_requested(job_id)
            job.cancel_requested = True
            if job.status is JobStatus.QUEUED:
                # Nothing has started, so this one is genuinely immediate.
                job.status = JobStatus.CANCELLED
                job.error_code = "CANCELLED"
                job.error_message = "Cancelled before the worker started it."
            else:
                job.status = JobStatus.CANCEL_REQUESTED
            return self.store.save_job(job)

    def pending(self) -> list[GenerationJob]:
        return self.store.queue_snapshot()

    def depth(self) -> int:
        return len(self.pending())

    def active(self) -> list[GenerationJob]:
        return [job for job in self.store.iter_jobs() if job.status.is_active]
