"""API -> queue -> worker -> artifacts, driven by the mock backend.

These never touch the GPU. The real model path is covered by
``scripts/smoke_test.py``.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from yue2_studio_core.models import JobStatus
from yue2_studio_core.store import Store


def run_worker_once() -> None:
    from services.yue2_worker.worker import Worker

    asyncio.run(Worker(once=True).run())


def test_a_queued_job_runs_to_completion_and_writes_every_artifact(api_client, sample_config):
    created = api_client.post("/api/v1/generations", json={"title": "Worker test", "config": sample_config})
    job_id = created.json()["generation"]["id"]

    run_worker_once()

    body = api_client.get(f"/api/v1/generations/{job_id}").json()["generation"]
    assert body["status"] == "COMPLETED"
    assert body["request_identity"]

    kinds = {artifact["kind"] for artifact in body["artifacts"]}
    assert {"audio", "score", "latent", "config", "manifest"} <= kinds

    audio = next(a for a in body["artifacts"] if a["kind"] == "audio")
    assert audio["sample_rate"] == 48000
    assert audio["channels"] == 2
    assert audio["duration_seconds"] and audio["duration_seconds"] > 0
    assert audio["sha256"]

    # Timings come from the worker, not from the request.
    assert body["timing"]["total_seconds"] > 0
    assert body["timing"]["output_seconds"] == pytest.approx(audio["duration_seconds"], rel=1e-6)


def test_the_manifest_explains_the_result(api_client, sample_config):
    job_id = api_client.post("/api/v1/generations", json={"config": sample_config}).json()["generation"]["id"]
    run_worker_once()

    manifest = api_client.get(f"/api/v1/generations/{job_id}/manifest").json()
    assert manifest["schema_version"] == 1
    assert manifest["generation_id"] == job_id
    assert manifest["finished_at"]
    assert manifest["request"]["sampling"]["seed"] == 4242
    assert manifest["effective_config"]
    assert manifest["weights"]
    assert manifest["runtime"]["backend"] == "mock"
    assert manifest["hardware"]["host"]["python"]
    assert manifest["manifest_identity"]


def test_audio_can_be_streamed_and_downloaded(api_client, sample_config):
    job_id = api_client.post("/api/v1/generations", json={"config": sample_config}).json()["generation"]["id"]
    run_worker_once()

    stream = api_client.get(f"/api/v1/artifacts/{job_id}/audio")
    assert stream.status_code == 200
    assert stream.headers["content-type"] == "audio/flac"
    assert len(stream.content) > 1000

    download = api_client.get(f"/api/v1/artifacts/{job_id}/download")
    assert "attachment" in download.headers["content-disposition"]
    assert job_id in download.headers["content-disposition"]


def test_the_score_is_stored_validated_and_editable(api_client, sample_config):
    job_id = api_client.post("/api/v1/generations", json={"config": sample_config}).json()["generation"]["id"]
    run_worker_once()

    bundle = api_client.get(f"/api/v1/scores/{job_id}").json()
    assert bundle["source"]["valid"] is True
    source = bundle["score"]["source_abc"]

    edited = source.replace('"C"', '"C7"')
    saved = api_client.put(f"/api/v1/scores/{job_id}", json={"edited_abc": edited})
    assert saved.status_code == 200
    # Reharmonising leaves the melody intact, which the comparison confirms.
    assert saved.json()["comparison"]["match"] is True

    rejected = api_client.put(f"/api/v1/scores/{job_id}", json={"edited_abc": "not a score"})
    assert rejected.status_code == 422

    regenerated = api_client.post(f"/api/v1/scores/{job_id}/regenerate", json={})
    assert regenerated.status_code == 201
    assert regenerated.json()["config"]["prompt"]["abc"].strip()


def test_progress_is_recorded_stage_by_stage_without_invented_percentages(
    api_client, sample_config, data_dir
):
    job_id = api_client.post("/api/v1/generations", json={"config": sample_config}).json()["generation"]["id"]

    observed: list[tuple[str, str, float | None, str | None]] = []
    stop = threading.Event()

    def watch() -> None:
        store = Store()
        while not stop.is_set():
            try:
                job = store.get_job(job_id)
            except Exception:
                time.sleep(0.02)
                continue
            entry = (job.status.value, job.progress.stage, job.progress.percent, job.progress.unit)
            if not observed or observed[-1] != entry:
                observed.append(entry)
            if job.status.is_terminal:
                return
            time.sleep(0.02)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    run_worker_once()
    watcher.join(timeout=5)  # the watcher exits by itself once the job is terminal
    stop.set()

    statuses = [entry[0] for entry in observed]
    for expected in ("PLANNING", "GENERATING", "DECODING", "POST_PROCESSING", "COMPLETED"):
        assert expected in statuses, f"{expected} never appeared in {statuses}"

    # Token stages have no genuine target, so they must not report a percentage.
    token_entries = [entry for entry in observed if entry[3] == "tokens"]
    assert token_entries
    assert all(entry[2] is None for entry in token_entries)

    # Stages with a real target do report one.
    step_entries = [entry for entry in observed if entry[3] in {"steps", "chunks"}]
    assert step_entries
    assert any(entry[2] is not None for entry in step_entries)


def test_cancelling_a_running_job_stops_it_and_records_why(api_client, sample_config):
    job_id = api_client.post("/api/v1/generations", json={"config": sample_config}).json()["generation"]["id"]

    def cancel_soon() -> None:
        store = Store()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                job = store.get_job(job_id)
            except Exception:
                time.sleep(0.02)
                continue
            if job.status is JobStatus.LOADING_MODEL:
                api_client.post(f"/api/v1/generations/{job_id}/cancel")
                return
            time.sleep(0.02)

    canceller = threading.Thread(target=cancel_soon, daemon=True)
    canceller.start()
    run_worker_once()
    canceller.join(timeout=5)

    job = api_client.get(f"/api/v1/generations/{job_id}").json()["generation"]
    assert job["status"] == "CANCELLED"
    assert job["error_code"] == "CANCELLED"

    failure = Store().generation_dir(job["project_id"], job_id) / "failure.json"
    assert failure.is_file()
    # The configuration the user asked for is preserved, unaltered.
    payload = json.loads(failure.read_text())
    assert payload["requested_config"]["sampling"]["seed"] == 4242


def test_the_queue_is_drained_in_order(api_client, sample_config):
    first = api_client.post("/api/v1/generations", json={"title": "one", "config": sample_config}).json()
    second = api_client.post(
        "/api/v1/generations", json={"title": "two", "priority": 5, "config": sample_config}
    ).json()

    run_worker_once()
    # The higher priority job is taken first even though it arrived second.
    assert api_client.get(f"/api/v1/generations/{second['generation']['id']}").json()["generation"]["status"] == "COMPLETED"
    assert api_client.get(f"/api/v1/generations/{first['generation']['id']}").json()["generation"]["status"] == "QUEUED"

    run_worker_once()
    assert api_client.get(f"/api/v1/generations/{first['generation']['id']}").json()["generation"]["status"] == "COMPLETED"


def test_generations_are_searchable_and_filterable(api_client, sample_config):
    api_client.post("/api/v1/generations", json={"title": "Piano ballad", "config": sample_config})
    run_worker_once()

    assert api_client.get("/api/v1/generations", params={"search": "piano"}).json()["total"] == 1
    assert api_client.get("/api/v1/generations", params={"search": "techno"}).json()["total"] == 0
    assert api_client.get("/api/v1/generations", params={"mode": "full"}).json()["total"] == 1
    assert api_client.get("/api/v1/generations", params={"status": ["COMPLETED"]}).json()["total"] == 1


def test_state_survives_a_restart(api_client, sample_config, data_dir):
    job_id = api_client.post("/api/v1/generations", json={"config": sample_config}).json()["generation"]["id"]
    run_worker_once()

    # A brand new Store over the same directory sees everything; there is no
    # in-memory state to lose.
    fresh = Store()
    reopened = fresh.get_job(job_id)
    assert reopened.status is JobStatus.COMPLETED
    assert fresh.absolute(reopened.audio_artifact().path).is_file()


# --------------------------------------------------------------------------- #
# Deletion
# --------------------------------------------------------------------------- #


def test_deleting_a_generation_removes_its_files_and_nothing_else(api_client, sample_config):
    keep = api_client.post("/api/v1/generations", json={"title": "keep", "config": sample_config}).json()
    run_worker_once()
    doomed = api_client.post("/api/v1/generations", json={"title": "doomed", "config": sample_config}).json()
    run_worker_once()

    store = Store()
    keep_id = keep["generation"]["id"]
    doomed_id = doomed["generation"]["id"]
    doomed_dir = store.generation_dir(doomed["generation"]["project_id"], doomed_id)
    keep_dir = store.generation_dir(keep["generation"]["project_id"], keep_id)
    assert doomed_dir.is_dir() and keep_dir.is_dir()

    response = api_client.delete(f"/api/v1/generations/{doomed_id}")
    assert response.status_code == 200
    report = response.json()
    assert report["deleted"] is True
    assert report["complete"] is True
    assert report["artifacts_removed"] > 0
    assert report["failures"] == []

    # Gone from disk and from the index.
    assert not doomed_dir.exists()
    assert not store.job_path(doomed_id).exists()
    assert api_client.get(f"/api/v1/generations/{doomed_id}").status_code == 404

    # The other generation is untouched.
    assert keep_dir.is_dir()
    assert api_client.get(f"/api/v1/generations/{keep_id}").status_code == 200
    assert store.absolute(store.get_job(keep_id).audio_artifact().path).is_file()


def test_deleting_leaves_no_orphan_files(api_client, sample_config):
    created = api_client.post("/api/v1/generations", json={"config": sample_config}).json()
    run_worker_once()
    generation = created["generation"]
    store = Store()
    directory = store.generation_dir(generation["project_id"], generation["id"])
    assert list(directory.rglob("*"))

    api_client.delete(f"/api/v1/generations/{generation['id']}")

    leftovers = [
        path
        for path in store.root.rglob("*")
        if generation["id"] in path.name or generation["id"] in str(path.parent)
    ]
    assert leftovers == [], f"orphans left behind: {leftovers}"


def test_a_running_generation_cannot_be_deleted(api_client, sample_config):
    created = api_client.post("/api/v1/generations", json={"config": sample_config}).json()
    response = api_client.delete(f"/api/v1/generations/{created['generation']['id']}")
    assert response.status_code == 409
    assert "cancel" in response.json()["error_message"].lower()


def test_deleting_the_current_generation_repoints_the_project(api_client, sample_config):
    first = api_client.post("/api/v1/generations", json={"config": sample_config}).json()
    run_worker_once()
    project_id = first["project"]["id"]
    second = api_client.post(
        "/api/v1/generations", json={"project_id": project_id, "config": sample_config}
    ).json()
    run_worker_once()

    store = Store()
    assert store.get_project(project_id).current_generation_id == second["generation"]["id"]

    api_client.delete(f"/api/v1/generations/{second['generation']['id']}")
    # The project falls back to the remaining generation rather than pointing
    # at something that no longer exists.
    assert store.get_project(project_id).current_generation_id == first["generation"]["id"]
