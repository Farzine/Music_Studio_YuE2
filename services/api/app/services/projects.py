"""Project lifecycle: rename, edit settings, delete.

A project is a container, not a generation. Nothing here starts a run or
touches a finished take: editing a project's settings changes what the *next*
take starts from, and every take already made keeps the snapshot it ran with.
"""
from __future__ import annotations

import logging
from typing import Any

from yue2_studio_core.errors import ConflictError, ValidationError
from yue2_studio_core.models import GenerationConfig, GenerationJob, JobStatus, SongProject
from yue2_studio_core.parameters import config_from_overrides, default_config
from yue2_studio_core.store import Store

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 120


class ProjectService:
    def __init__(self, *, store: Store) -> None:
        self.store = store

    # -- reads ------------------------------------------------------------- #

    def generations(self, project_id: str) -> list[GenerationJob]:
        """Every take in the project, newest first."""
        jobs = [job for job in self.store.iter_jobs() if job.project_id == project_id]
        jobs.sort(key=lambda job: (job.version, job.requested_at), reverse=True)
        return jobs

    def starting_config(self, project_id: str) -> tuple[GenerationConfig, str]:
        """The configuration the settings editor should open with.

        Preference order, and the reason for it: the project's own saved
        settings if it has any, otherwise the most recent take's snapshot so
        the editor reflects what this song actually sounds like, otherwise the
        studio defaults.
        """
        project = self.store.get_project(project_id)
        if project.default_config is not None:
            return project.default_config, "project"
        for job in self.generations(project_id):
            return job.config, "latest_generation"
        return default_config(), "defaults"

    # -- writes ------------------------------------------------------------ #

    @staticmethod
    def clean_title(title: str) -> str:
        cleaned = " ".join(title.split())
        if not cleaned:
            raise ValidationError(
                "A project needs a name.", details={"parameter": "title"}
            )
        if len(cleaned) > MAX_TITLE_LENGTH:
            raise ValidationError(
                f"A project name can be at most {MAX_TITLE_LENGTH} characters.",
                details={"parameter": "title", "length": len(cleaned)},
            )
        return cleaned

    def rename(self, project_id: str, title: str) -> SongProject:
        project = self.store.get_project(project_id)
        project.title = self.clean_title(title)
        return self.store.save_project(project)

    def update_settings(self, project_id: str, overrides: dict[str, Any]) -> SongProject:
        """Store the settings new takes in this project start from.

        The overrides are merged over the studio defaults and validated by the
        same model the generation endpoint uses, so an impossible value is
        rejected here rather than at generation time. The project's own style,
        lyrics and mode follow the configuration, because those are the fields
        the project page shows.
        """
        project = self.store.get_project(project_id)
        config = config_from_overrides(overrides)
        project.default_config = config
        project.style = config.prompt.style
        project.lyrics = config.prompt.lyrics
        project.mode = config.prompt.mode
        return self.store.save_project(project)

    def update_metadata(self, project_id: str, fields: dict[str, Any]) -> SongProject:
        """Apply plain metadata: description, tags, favourite, title."""
        project = self.store.get_project(project_id)
        for key, value in fields.items():
            if key == "title":
                value = self.clean_title(value)
            setattr(project, key, value)
        return self.store.save_project(project)

    def delete(self, project_id: str) -> dict:
        """Delete a project with every take inside it.

        The project is read first so the response can say what went, and a
        partial failure is reported rather than swallowed: a caller told
        "deleted" while files remain would never look for the leftovers.
        """
        project = self.store.get_project(project_id)
        takes = self.generations(project_id)
        running = [
            job for job in takes if job.status.is_active or job.status is JobStatus.QUEUED
        ]
        if running:
            raise ConflictError(
                f"{len(running)} generation(s) in this project are still running. "
                "Cancel them first, then delete the project."
            )
        report = self.store.delete_project(project_id)
        if not report["complete"]:
            logger.error("project %s was deleted with leftovers: %s", project_id, report["failed"])
        return {
            "deleted": True,
            "project_id": project_id,
            "title": project.title,
            "generations_removed": len(report["generations_removed"]),
            "generation_ids": report["generations_removed"],
            "had_generations": len(takes),
            "complete": report["complete"],
            "failures": report["failed"],
        }
