"""Job state machine, queue ordering and artifact paths."""
from __future__ import annotations

import pytest

from yue2_studio_core.errors import ConflictError
from yue2_studio_core.ids import is_valid_id, new_id
from yue2_studio_core.models import GenerationJob, JobStatus, can_transition


def test_only_declared_transitions_are_allowed():
    assert can_transition(JobStatus.QUEUED, JobStatus.LOADING_MODEL)
    assert can_transition(JobStatus.GENERATING, JobStatus.DECODING)
    assert can_transition(JobStatus.CANCEL_REQUESTED, JobStatus.CANCELLED)
    assert not can_transition(JobStatus.QUEUED, JobStatus.COMPLETED)
    assert not can_transition(JobStatus.COMPLETED, JobStatus.GENERATING)
    assert not can_transition(JobStatus.FAILED, JobStatus.QUEUED)


def test_terminal_and_active_classification():
    assert JobStatus.COMPLETED.is_terminal
    assert JobStatus.CANCELLED.is_terminal
    assert not JobStatus.QUEUED.is_active
    assert JobStatus.DECODING.is_active


def test_store_refuses_an_impossible_transition(store):
    project = store.create_project(title="p")
    job = GenerationJob(id=new_id("gen"), project_id=project.id)
    store.save_job(job)
    with pytest.raises(ConflictError):
        store.transition(job, JobStatus.COMPLETED)


def test_identifiers_are_sortable_and_path_safe():
    first = new_id("gen")
    second = new_id("gen")
    assert is_valid_id(first)
    assert first < second or first[:12] == second[:12]
    assert not is_valid_id("../escape")
    assert not is_valid_id("gen_/etc/passwd")


def test_artifact_paths_are_deterministic(store):
    project = store.create_project(title="p")
    job = GenerationJob(id=new_id("gen"), project_id=project.id)
    directory = store.prepare_generation_dir(project.id, job.id)
    assert directory == store.root / "projects" / project.id / "generations" / job.id
    for name in ("audio", "score", "intermediates", "logs"):
        assert (directory / name).is_dir()


def test_paths_outside_the_data_directory_are_refused(store):
    with pytest.raises(Exception):
        store.absolute("../../etc/passwd")


def test_queue_orders_by_priority_then_request_time(store, queue):
    project = store.create_project(title="p")
    low = GenerationJob(id=new_id("gen"), project_id=project.id, title="low")
    high = GenerationJob(id=new_id("gen"), project_id=project.id, title="high", priority=5)
    queue.enqueue(low)
    queue.enqueue(high)
    assert [job.title for job in queue.pending()] == ["high", "low"]


def test_one_gpu_job_at_a_time(store, queue):
    project = store.create_project(title="p")
    for index in range(3):
        queue.enqueue(GenerationJob(id=new_id("gen"), project_id=project.id, title=f"job {index}"))

    first = queue.claim("worker-a")
    assert first is not None
    assert first.status is JobStatus.LOADING_MODEL
    # The limit is one, so nothing else is handed out while that job runs.
    assert queue.claim("worker-a") is None
    assert queue.depth() == 2

    store.transition(first, JobStatus.FAILED, strict=False)
    assert queue.claim("worker-a") is not None


def test_cancelling_a_queued_job_is_immediate(store, queue):
    project = store.create_project(title="p")
    job = GenerationJob(id=new_id("gen"), project_id=project.id)
    queue.enqueue(job)
    cancelled = queue.request_cancel(job.id)
    assert cancelled.status is JobStatus.CANCELLED
    assert queue.depth() == 0


def test_cancelling_a_running_job_only_requests_it(store, queue):
    project = store.create_project(title="p")
    job = GenerationJob(id=new_id("gen"), project_id=project.id)
    queue.enqueue(job)
    claimed = queue.claim("worker-a")
    assert claimed is not None
    requested = queue.request_cancel(claimed.id)
    # Cancellation is cooperative: the worker stops at its next safe boundary.
    assert requested.status is JobStatus.CANCEL_REQUESTED
    assert requested.cancel_requested is True
