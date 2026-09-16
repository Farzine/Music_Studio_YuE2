"""Generation orchestration on the API side.

This module creates and validates jobs and hands them to the queue. It never
loads a model and never runs inference; that belongs to the worker process.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from yue2_studio_core.abc import validate as validate_abc
from yue2_studio_core.errors import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    StudioError,
    UnsupportedCapabilityError,
    ValidationError,
)
from yue2_studio_core.ids import new_id
from yue2_studio_core.models import (
    GenerationConfig,
    GenerationJob,
    GenerationMode,
    JobStatus,
    ProgressState,
    SeedBehavior,
    SongProject,
    utcnow,
)
from yue2_studio_core.parameters import config_from_overrides, unsupported_parameters_in_use
from yue2_studio_core.queue import FilesystemJobQueue
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store

from app.services.capabilities import CapabilityService

logger = logging.getLogger(__name__)

MAX_SEED = 2**63 - 1


class GenerationService:
    def __init__(
        self,
        *,
        store: Store,
        queue: FilesystemJobQueue,
        capabilities: CapabilityService,
        settings: Settings,
    ) -> None:
        self.store = store
        self.queue = queue
        self.capabilities = capabilities
        self.settings = settings

    # -- validation -------------------------------------------------------- #

    def validate_config(self, config: GenerationConfig) -> list[str]:
        """Server-side validation. Frontend checks are a convenience, not a gate."""
        backend = self.settings.yue2_backend
        capabilities = self.capabilities.capabilities(backend)
        warnings: list[str] = []

        if not config.prompt.style.strip():
            raise ValidationError("A style description is required.")
        if config.prompt.mode is not GenerationMode.OFF and not config.prompt.lyrics.strip():
            raise ValidationError("Lyrics are required unless you choose Direct Audio.")

        mode = config.prompt.mode
        if mode.value not in capabilities["modes"]:
            entry = capabilities["capabilities"].get(mode.value, {})
            raise UnsupportedCapabilityError(
                f"Mode '{mode.value}' is not available: {entry.get('reason', 'not advertised by the active backend')}",
                details={"mode": mode.value},
            )

        if config.prompt.abc.strip():
            validate_abc(config.prompt.abc)  # raises AbcValidationError with the reason

        self._validate_model(config)
        self._validate_reference_audio(config)

        violations = unsupported_parameters_in_use(config, backend)
        if violations:
            raise UnsupportedCapabilityError(
                "These settings have no equivalent in the active backend: "
                + ", ".join(f"{item['label']} ({item['reason']})" for item in violations),
                details={"parameters": violations},
            )

        if config.model.quantization != "none":
            entry = capabilities["capabilities"].get("quantization_fp8", {})
            if not entry.get("supported"):
                raise UnsupportedCapabilityError(
                    f"FP8 is not available: {entry.get('reason', 'unsupported')}",
                    details={"parameter": "model.quantization"},
                )
        if config.model.compute_backend == "vllm":
            entry = capabilities["capabilities"].get("backend_vllm", {})
            if not entry.get("supported"):
                raise UnsupportedCapabilityError(
                    f"The vLLM backend is not available: {entry.get('reason', 'unsupported')}",
                    details={"parameter": "model.compute_backend"},
                )
        if config.model.vae == "legacy":
            entry = capabilities["capabilities"].get("vae_legacy", {})
            if not entry.get("supported"):
                raise UnsupportedCapabilityError(
                    f"The legacy decoder is not available: {entry.get('reason', 'unsupported')}",
                    details={"parameter": "model.vae"},
                )
        if config.output.format.value == "mp3":
            entry = capabilities["capabilities"].get("output_mp3", {})
            if not entry.get("supported"):
                raise UnsupportedCapabilityError(
                    f"MP3 delivery is not available: {entry.get('reason', 'unsupported')}",
                    details={"parameter": "output.format"},
                )

        if config.sampling.min_tokens > config.sampling.max_tokens:
            raise ValidationError("The minimum length is longer than the maximum duration.")
        if config.decoder.mode.value == "full" and config.sampling.effective_duration_seconds > 300:
            warnings.append(
                "Whole-song decoding of a long track can exhaust VRAM. The tiled decoder is the safe choice."
            )
        if config.prompt.lyrics and len(config.prompt.lyrics) > 8000:
            warnings.append("Very long lyrics can crowd the context window and lead to a truncated plan.")
        return warnings

    def _validate_model(self, config: GenerationConfig) -> None:
        """Refuse an unknown or incomplete model, naming the actual problem."""
        entry = self.capabilities.resolve_model_choice(config.model.checkpoint)
        if entry is None:
            available = [
                item["id"] for item in self.capabilities.local_models() if item["role"] == "model"
            ]
            raise ValidationError(
                f"The selected model '{config.model.checkpoint}' is not one this installation knows about.",
                details={"parameter": "model.checkpoint", "available": available},
            )
        if not entry["present"]:
            raise StudioError(
                ErrorCode.MODEL_NOT_FOUND,
                f"The selected model '{entry['label']}' cannot be loaded: {entry['problem']}",
                details={
                    "parameter": "model.checkpoint",
                    "model": entry["id"],
                    "path": entry["path"],
                    "problem": entry["problem"],
                },
            )

    def _validate_reference_audio(self, config: GenerationConfig) -> None:
        """Cover mode: the upload has to exist and be readable, now, not later."""
        upload_id = config.prompt.reference_upload_id
        if not upload_id:
            return
        try:
            upload = self.store.get_upload(upload_id)
        except NotFoundError as exc:
            raise StudioError(
                ErrorCode.AUDIO_INPUT_ERROR,
                "The reference audio upload no longer exists. Upload the file again.",
                details={"parameter": "prompt.reference_upload_id", "upload_id": upload_id},
            ) from exc
        path = self.store.absolute(upload.path)
        if not path.is_file():
            raise StudioError(
                ErrorCode.AUDIO_INPUT_ERROR,
                "The reference audio file is missing from disk. Upload it again.",
                details={"parameter": "prompt.reference_upload_id", "upload_id": upload_id},
            )
        if upload.duration_seconds is not None and upload.duration_seconds < 5:
            raise StudioError(
                ErrorCode.AUDIO_INPUT_ERROR,
                "The reference audio is shorter than five seconds, which is too little to transcribe.",
                details={"parameter": "prompt.reference_upload_id", "duration": upload.duration_seconds},
            )

    # -- seed ------------------------------------------------------------- #

    @staticmethod
    def resolve_seed(config: GenerationConfig) -> int:
        """Apply the seed behaviour on the server and return the seed used."""
        behaviour = config.sampling.control_after_generate
        if behaviour is SeedBehavior.RANDOMIZE:
            return secrets.randbelow(MAX_SEED)
        if behaviour is SeedBehavior.INCREMENT:
            return (config.sampling.seed + 1) % MAX_SEED
        return config.sampling.seed

    # -- creation ---------------------------------------------------------- #

    def create_generation(
        self,
        *,
        overrides: dict[str, Any] | None,
        project_id: str | None = None,
        title: str = "",
        tags: list[str] | None = None,
        priority: int = 0,
    ) -> tuple[GenerationJob, SongProject, list[str]]:
        config = config_from_overrides(overrides)
        warnings = self.validate_config(config)

        # The seed that will actually be used is decided here, recorded in the
        # config, and shown back to the user. The runtime never sees a mode.
        config.sampling.seed = self.resolve_seed(config)
        config.sampling.control_after_generate = SeedBehavior.FIXED

        if project_id:
            project = self.store.get_project(project_id)
        else:
            project = self.store.create_project(
                title=title or self._derive_title(config),
                style=config.prompt.style,
                lyrics=config.prompt.lyrics,
                mode=config.prompt.mode,
                tags=tags or [],
            )

        job = GenerationJob(
            id=new_id("gen"),
            project_id=project.id,
            title=title or project.title or self._derive_title(config),
            config=config,
            priority=priority,
            warnings=warnings,
            progress=ProgressState(stage="queued", label="Queued"),
        )
        directory = self.store.prepare_generation_dir(project.id, job.id)
        self.store.append_log(job, "INFO", "queued", f"Generation queued with seed {config.sampling.seed}.")
        (directory / "request.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")

        self.queue.enqueue(job)
        project.current_generation_id = job.id
        self.store.save_project(project)
        return job, project, warnings

    @staticmethod
    def _derive_title(config: GenerationConfig) -> str:
        style = config.prompt.style.strip().splitlines()[0] if config.prompt.style.strip() else "Untitled"
        return (style[:57] + "...") if len(style) > 60 else style

    # -- lifecycle --------------------------------------------------------- #

    def cancel(self, generation_id: str) -> GenerationJob:
        return self.queue.request_cancel(generation_id)

    def retry(self, generation_id: str) -> GenerationJob:
        original = self.store.get_job(generation_id)
        if not original.status.is_terminal:
            raise ConflictError("Only a finished generation can be retried.")
        job, _, _ = self.create_generation(
            overrides=original.config.model_dump(mode="json"),
            project_id=original.project_id,
            title=original.title,
            priority=original.priority,
        )
        return job

    def duplicate(self, generation_id: str, overrides: dict[str, Any] | None = None) -> GenerationJob:
        """Re-run with the same configuration, optionally with changes on top."""
        original = self.store.get_job(generation_id)
        base = original.config.model_dump(mode="json")
        merged = base if not overrides else _deep_merge(base, overrides)
        job, _, _ = self.create_generation(
            overrides=merged,
            project_id=original.project_id,
            title=original.title,
        )
        return job

    # -- queries ----------------------------------------------------------- #

    def list_generations(
        self,
        *,
        project_id: str | None = None,
        status: list[str] | None = None,
        mode: str | None = None,
        search: str | None = None,
        favorite: bool | None = None,
        min_duration: float | None = None,
        max_duration: float | None = None,
        model: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        jobs = self.store.list_jobs()
        statuses = {value.upper() for value in status} if status else None
        needle = search.lower().strip() if search else None

        def matches(job: GenerationJob) -> bool:
            if project_id and job.project_id != project_id:
                return False
            if statuses and job.status.value not in statuses:
                return False
            if mode and job.config.prompt.mode.value != mode:
                return False
            if favorite is not None and job.favorite != favorite:
                return False
            if model and job.config.model.checkpoint != model:
                return False
            audio = job.audio_artifact()
            duration = audio.duration_seconds if audio else None
            if min_duration is not None and (duration is None or duration < min_duration):
                return False
            if max_duration is not None and (duration is None or duration > max_duration):
                return False
            if needle:
                haystack = " ".join(
                    [job.title, job.config.prompt.style, job.config.prompt.lyrics, job.id]
                ).lower()
                if needle not in haystack:
                    return False
            return True

        filtered = [job for job in jobs if matches(job)]
        filtered.sort(key=lambda job: job.requested_at, reverse=True)
        window = filtered[offset : offset + limit]
        return {"total": len(filtered), "limit": limit, "offset": offset, "items": window}

    def queue_view(self) -> dict:
        pending = self.queue.pending()
        active = self.queue.active()
        now = utcnow()
        return {
            "active": [
                {
                    "id": job.id,
                    "title": job.title,
                    "status": job.status.value,
                    "progress": job.progress.model_dump(mode="json"),
                    "elapsed_seconds": (now - (job.started_at or job.requested_at)).total_seconds(),
                    "worker_id": job.worker_id,
                    "priority": job.priority,
                }
                for job in active
            ],
            "queued": [
                {
                    "id": job.id,
                    "title": job.title,
                    "queue_position": job.queue_position,
                    "priority": job.priority,
                    "waiting_seconds": (now - job.requested_at).total_seconds(),
                }
                for job in pending
            ],
            "depth": len(pending),
            "max_concurrent_gpu_jobs": self.settings.max_concurrent_gpu_jobs,
        }

    def set_favorite(self, generation_id: str, favorite: bool) -> GenerationJob:
        job = self.store.get_job(generation_id)
        job.favorite = favorite
        return self.store.save_job(job)

    def rename(self, generation_id: str, title: str) -> GenerationJob:
        job = self.store.get_job(generation_id)
        job.title = title
        return self.store.save_job(job)

    def delete(self, generation_id: str) -> dict:
        """Delete a generation and everything belonging to it.

        Only this generation's own directory is touched: model files, shared
        caches, other projects and other generations are never involved.
        """
        job = self.store.get_job(generation_id)
        if job.status.is_active or job.status is JobStatus.QUEUED:
            raise ConflictError(
                "This generation is still running. Cancel it first, then delete it."
            )
        report = self.store.delete_generation_artifacts(job.project_id, job.id)

        project = self.store.get_project(job.project_id)
        if project.current_generation_id == job.id:
            remaining = [
                other
                for other in self.store.iter_jobs()
                if other.project_id == project.id and other.id != job.id
            ]
            remaining.sort(key=lambda other: other.requested_at, reverse=True)
            project.current_generation_id = remaining[0].id if remaining else None
            self.store.save_project(project)

        if not report["complete"]:
            logger.error(
                "generation %s was deleted with leftovers: %s", generation_id, report["failed"]
            )
        return {
            "deleted": True,
            "generation_id": generation_id,
            "artifacts_removed": len(report["removed"]),
            "complete": report["complete"],
            "failures": report["failed"],
        }

    def manifest(self, generation_id: str) -> dict:
        job = self.store.get_job(generation_id)
        path = self.store.generation_dir(job.project_id, job.id) / "manifest.json"
        if not path.is_file():
            raise NotFoundError("No manifest has been written for this generation yet.")
        import json

        return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: dict, overrides: dict) -> dict:
    import copy

    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
