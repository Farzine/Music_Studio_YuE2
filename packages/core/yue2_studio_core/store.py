"""Filesystem store.

There is no database. Projects, generations, jobs, scores, uploads and presets
are JSON documents under ``DATA_DIR``; audio, latents and logs are ordinary
files next to them. Every write is atomic (temporary file plus ``os.replace``)
so a crash never leaves a half-written record, and the queue is serialised with
an advisory lock on a single file.

The layout is deterministic:

    data/
      projects/<project-id>/project.json
      projects/<project-id>/generations/<generation-id>/
          request.json effective_config.json manifest.json
          audio/ score/ intermediates/ logs/
      jobs/<job-id>.json
      uploads/<upload-id>/
      presets/<preset-id>.json
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel

from .errors import ConflictError, NotFoundError
from .ids import is_valid_id, new_id
from .models import (
    GenerationJob,
    JobStatus,
    Preset,
    Score,
    SongProject,
    Upload,
    can_transition,
    utcnow,
)
from .settings import Settings, get_settings

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, *, fallback: str = "file") -> str:
    """Strip directories and anything that is not a plain filename character."""
    base = Path(name).name
    cleaned = _UNSAFE.sub("_", base).strip("._") or fallback
    return cleaned[:120]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


def _dump(model: BaseModel) -> dict:
    return json.loads(model.model_dump_json())


class Store:
    """Everything the studio persists, over a plain directory tree."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = self.settings.data_path
        self.ensure_layout()

    # -- layout ---------------------------------------------------------- #

    def ensure_layout(self) -> None:
        for name in ("projects", "jobs", "uploads", "presets", "tmp"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def jobs_dir(self) -> Path:
        return self.root / "jobs"

    @property
    def uploads_dir(self) -> Path:
        return self.root / "uploads"

    @property
    def presets_dir(self) -> Path:
        return self.root / "presets"

    def project_dir(self, project_id: str) -> Path:
        self._check_id(project_id)
        return self.projects_dir / project_id

    def generation_dir(self, project_id: str, generation_id: str) -> Path:
        self._check_id(generation_id)
        return self.project_dir(project_id) / "generations" / generation_id

    def relative(self, path: Path) -> str:
        return str(Path(path).resolve().relative_to(self.root))

    def absolute(self, relative_path: str) -> Path:
        """Resolve a stored relative path, refusing anything outside DATA_DIR."""
        candidate = (self.root / relative_path).resolve()
        if not str(candidate).startswith(str(self.root.resolve()) + os.sep):
            raise NotFoundError("path outside the data directory")
        return candidate

    @staticmethod
    def _check_id(value: str) -> None:
        if not is_valid_id(value):
            raise NotFoundError(f"invalid identifier: {value!r}")

    # -- runtime settings ------------------------------------------------ #

    @property
    def runtime_settings_path(self) -> Path:
        return self.root / "runtime-settings.json"

    def read_runtime_settings(self) -> dict:
        """Settings the user can change while the application is running.

        These live in the data directory rather than .env because the System
        page writes them: the worker picks them up on its next job without a
        restart, and a wrong value can be corrected from the UI.
        """
        path = self.runtime_settings_path
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def write_runtime_settings(self, values: dict) -> dict:
        current = self.read_runtime_settings()
        current.update(values)
        current["schema_version"] = 1
        current["updated_at"] = utcnow().isoformat()
        write_json_atomic(self.runtime_settings_path, current)
        return current

    def device_index(self, default: int = 0) -> int:
        """Which visible CUDA device the worker should use."""
        value = self.read_runtime_settings().get("device_index", default)
        try:
            index = int(value)
        except (TypeError, ValueError):
            return default
        return index if index >= 0 else default

    # -- projects -------------------------------------------------------- #

    def create_project(self, **fields) -> SongProject:
        project = SongProject(id=new_id("prj"), **fields)
        self.save_project(project)
        return project

    def save_project(self, project: SongProject) -> SongProject:
        project.updated_at = utcnow()
        write_json_atomic(self.project_dir(project.id) / "project.json", _dump(project))
        return project

    def get_project(self, project_id: str) -> SongProject:
        path = self.project_dir(project_id) / "project.json"
        if not path.is_file():
            raise NotFoundError(f"project {project_id} not found")
        return SongProject.model_validate_json(path.read_text(encoding="utf-8"))

    def list_projects(self) -> list[SongProject]:
        projects = []
        for directory in sorted(self.projects_dir.iterdir(), reverse=True) if self.projects_dir.exists() else []:
            path = directory / "project.json"
            if path.is_file():
                projects.append(SongProject.model_validate_json(path.read_text(encoding="utf-8")))
        return projects

    def delete_generation_artifacts(self, project_id: str, generation_id: str) -> dict:
        """Remove a generation's directory, reporting precisely what happened.

        A partial failure is returned rather than swallowed: claiming a clean
        delete while files remain on disk would leave orphans nobody looks for.
        """
        directory = self.generation_dir(project_id, generation_id)
        report: dict = {"directory": str(directory), "existed": directory.is_dir(), "removed": [], "failed": []}
        if directory.is_dir():
            for path in sorted(directory.rglob("*"), reverse=True):
                try:
                    if path.is_dir() and not path.is_symlink():
                        path.rmdir()
                    else:
                        path.unlink()
                    report["removed"].append(str(path.relative_to(directory)))
                except OSError as exc:
                    report["failed"].append({"path": str(path.relative_to(directory)), "error": str(exc)})
            try:
                directory.rmdir()
            except OSError as exc:
                report["failed"].append({"path": ".", "error": str(exc)})
        for path in (self.job_path(generation_id), self.cancel_marker_path(generation_id)):
            try:
                if path.exists():
                    path.unlink()
                    report["removed"].append(path.name)
            except OSError as exc:
                report["failed"].append({"path": path.name, "error": str(exc)})
        report["complete"] = not report["failed"]
        return report

    def delete_project(self, project_id: str) -> None:
        directory = self.project_dir(project_id)
        if not directory.is_dir():
            raise NotFoundError(f"project {project_id} not found")
        for job in self.list_jobs():
            if job.project_id == project_id:
                (self.jobs_dir / f"{job.id}.json").unlink(missing_ok=True)
                self.cancel_marker_path(job.id).unlink(missing_ok=True)
        shutil.rmtree(directory)

    # -- jobs / generations ---------------------------------------------- #

    def job_path(self, job_id: str) -> Path:
        self._check_id(job_id)
        return self.jobs_dir / f"{job_id}.json"

    def cancel_marker_path(self, job_id: str) -> Path:
        self._check_id(job_id)
        return self.jobs_dir / f"{job_id}.cancel"

    def mark_cancel_requested(self, job_id: str) -> None:
        """Record a cancellation as its own file.

        The worker rewrites the job document continuously while it reports
        progress. If the request lived only in that document, the next progress
        write from the worker's in-memory copy would erase it. A separate
        marker cannot be lost that way.
        """
        self.cancel_marker_path(job_id).touch()

    def is_cancel_requested(self, job_id: str) -> bool:
        return self.cancel_marker_path(job_id).exists()

    def save_job(self, job: GenerationJob) -> GenerationJob:
        job.updated_at = utcnow()
        # Never let a stale in-memory copy drop a cancellation that arrived
        # while this job was running.
        if self.is_cancel_requested(job.id):
            job.cancel_requested = True
        payload = _dump(job)
        write_json_atomic(self.job_path(job.id), payload)
        directory = self.generation_dir(job.project_id, job.id)
        if directory.is_dir():
            # Keep a copy inside the artifact directory so a generation folder
            # is self-describing when copied elsewhere.
            write_json_atomic(directory / "job.json", payload)
        return job

    def get_job(self, job_id: str) -> GenerationJob:
        path = self.job_path(job_id)
        if not path.is_file():
            raise NotFoundError(f"generation {job_id} not found")
        return GenerationJob.model_validate_json(path.read_text(encoding="utf-8"))

    def iter_jobs(self) -> Iterator[GenerationJob]:
        if not self.jobs_dir.is_dir():
            return
        for path in sorted(self.jobs_dir.glob("*.json"), reverse=True):
            try:
                yield GenerationJob.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                # A record being rewritten right now is skipped, not fatal.
                continue

    def list_jobs(self) -> list[GenerationJob]:
        return list(self.iter_jobs())

    def transition(self, job: GenerationJob, status: JobStatus, *, strict: bool = True) -> GenerationJob:
        if job.status is status:
            return job
        if strict and not can_transition(job.status, status):
            raise ConflictError(f"cannot move generation {job.id} from {job.status.value} to {status.value}")
        job.status = status
        if status is JobStatus.LOADING_MODEL and job.started_at is None:
            job.started_at = utcnow()
        if status is JobStatus.COMPLETED:
            job.finished_at = utcnow()
        if status is JobStatus.FAILED:
            job.failed_at = utcnow()
            job.finished_at = utcnow()
        if status is JobStatus.CANCELLED:
            job.finished_at = utcnow()
        return self.save_job(job)

    def queue_snapshot(self) -> list[GenerationJob]:
        """Queued jobs in the order the worker will claim them."""
        queued = [job for job in self.iter_jobs() if job.status is JobStatus.QUEUED]
        queued.sort(key=lambda job: (-job.priority, job.requested_at))
        for position, job in enumerate(queued, start=1):
            job.queue_position = position
        return queued

    @contextmanager
    def queue_lock(self) -> Iterator[None]:
        """Advisory lock serialising job claims across processes."""
        lock_path = self.jobs_dir / ".queue.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

    def claim_next_job(self, worker_id: str, *, max_concurrent: int = 1) -> GenerationJob | None:
        """Atomically take the next queued job, respecting the GPU limit."""
        with self.queue_lock():
            jobs = self.list_jobs()
            running = [job for job in jobs if job.status.is_active and job.worker_id == worker_id]
            if len(running) >= max_concurrent:
                return None
            queued = sorted(
                (job for job in jobs if job.status is JobStatus.QUEUED),
                key=lambda job: (-job.priority, job.requested_at),
            )
            for job in queued:
                if job.cancel_requested or self.is_cancel_requested(job.id):
                    job.status = JobStatus.CANCELLED
                    job.finished_at = utcnow()
                    job.error_code = "CANCELLED"
                    self.save_job(job)
                    continue
                job.worker_id = worker_id
                job.queue_position = None
                job.timing.queue_wait_seconds = (utcnow() - job.requested_at).total_seconds()
                job.status = JobStatus.LOADING_MODEL
                job.started_at = utcnow()
                return self.save_job(job)
        return None

    # -- generation artifacts -------------------------------------------- #

    def prepare_generation_dir(self, project_id: str, generation_id: str) -> Path:
        directory = self.generation_dir(project_id, generation_id)
        for name in ("audio", "score", "intermediates", "logs"):
            (directory / name).mkdir(parents=True, exist_ok=True)
        return directory

    def append_log(self, job: GenerationJob, severity: str, stage: str, message: str) -> None:
        """Structured job log line: job, generation, stage, timestamp, severity."""
        directory = self.generation_dir(job.project_id, job.id) / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": utcnow().isoformat(),
            "job_id": job.id,
            "generation_id": job.id,
            "project_id": job.project_id,
            "stage": stage,
            "severity": severity,
            "message": message,
        }
        with open(directory / "generation.log", "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_log(self, job: GenerationJob, limit: int = 500) -> list[dict]:
        path = self.generation_dir(job.project_id, job.id) / "logs" / "generation.log"
        if not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    # -- scores ----------------------------------------------------------- #

    def save_score(self, score: Score) -> Score:
        score.updated_at = utcnow()
        directory = self.generation_dir(score.project_id, score.generation_id) / "score"
        directory.mkdir(parents=True, exist_ok=True)
        write_text_atomic(directory / "source.abc", score.source_abc)
        if score.edited_abc is not None:
            write_text_atomic(directory / "edited.abc", score.edited_abc)
        write_json_atomic(directory / "score.json", _dump(score))
        return score

    def get_score(self, generation_id: str) -> Score:
        job = self.get_job(generation_id)
        path = self.generation_dir(job.project_id, generation_id) / "score" / "score.json"
        if not path.is_file():
            raise NotFoundError(f"no score stored for generation {generation_id}")
        return Score.model_validate_json(path.read_text(encoding="utf-8"))

    # -- uploads ---------------------------------------------------------- #

    def save_upload(self, filename: str, payload: bytes, content_type: str) -> Upload:
        upload_id = new_id("upl")
        directory = self.uploads_dir / upload_id
        directory.mkdir(parents=True, exist_ok=True)
        name = safe_filename(filename, fallback="reference.wav")
        target = directory / name
        target.write_bytes(payload)
        upload = Upload(
            id=upload_id,
            filename=name,
            path=self.relative(target),
            bytes=len(payload),
            content_type=content_type,
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        write_json_atomic(directory / "upload.json", _dump(upload))
        return upload

    def get_upload(self, upload_id: str) -> Upload:
        path = self.uploads_dir / upload_id / "upload.json"
        if not path.is_file():
            raise NotFoundError(f"upload {upload_id} not found")
        return Upload.model_validate_json(path.read_text(encoding="utf-8"))

    # -- presets ---------------------------------------------------------- #

    def save_preset(self, preset: Preset) -> Preset:
        preset.updated_at = utcnow()
        write_json_atomic(self.presets_dir / f"{preset.id}.json", _dump(preset))
        return preset

    def list_user_presets(self) -> list[Preset]:
        if not self.presets_dir.is_dir():
            return []
        presets = []
        for path in sorted(self.presets_dir.glob("*.json")):
            presets.append(Preset.model_validate_json(path.read_text(encoding="utf-8")))
        return presets

    def delete_preset(self, preset_id: str) -> None:
        path = self.presets_dir / f"{preset_id}.json"
        if not path.is_file():
            raise NotFoundError(f"preset {preset_id} not found")
        path.unlink()
