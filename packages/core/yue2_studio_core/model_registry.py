"""Durable installation facts; readiness and GPU residency are never persisted."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import NotFoundError, ValidationError
from .model_metadata import ModelFacts, ModelMetadata, describe_model_files
from .model_validator import ValidationReport, file_fingerprint, validation_files
from .models import utcnow
from .settings import Settings
from .store import Store, file_lock, write_json_atomic


def _identity(reference: str, role: str) -> str:
    return "model_" + hashlib.sha256(f"{role}\0{reference}".encode()).hexdigest()[:24]


class ModelRecord(ModelFacts):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    reference: str
    role: Literal["model", "vae"]
    aliases: list[str]
    created_at: datetime
    updated_at: datetime
    deletion_status: Literal["active", "deleting"] = "active"
    trash_path: str | None = None

    @model_validator(mode="after")
    def valid_identity(self) -> ModelRecord:
        if not Path(self.reference).is_absolute() or self.registry_id != _identity(self.reference, self.role):
            raise ValueError("Invalid installation identity or absolute reference.")
        if self.reference not in self.aliases or any(not Path(alias).is_absolute() for alias in self.aliases):
            raise ValueError("Installation aliases must be absolute paths and include its reference.")
        if self.format == "gguf" and not self.filename:
            raise ValueError("GGUF installations require a filename.")
        if self.filename and (Path(self.filename).is_absolute() or ".." in Path(self.filename).parts):
            raise ValueError("The model filename must be inside its installation directory.")
        if self.trash_path is not None and self.trash_path != str(Path(self.reference).with_name(f".{self.registry_id}.deleting")):
            raise ValueError("Invalid model deletion staging path.")
        return self


class RegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    entries: list[ModelRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> RegistryDocument:
        if len({item.registry_id for item in self.entries}) != len(self.entries):
            raise ValueError("Duplicate installation identities.")
        return self


class ModelRegistry:
    def __init__(self, settings: Settings, store: Store | None = None) -> None:
        self.settings = settings
        self.store = store or Store(settings)
        self.path = self.store.root / "model-registry.json"
        self.lock_path = self.store.root / ".model-registry.lock"

    def _read(self) -> RegistryDocument:
        try:
            return RegistryDocument.model_validate_json(self.path.read_text(encoding="utf-8"), strict=True)
        except FileNotFoundError:
            return RegistryDocument()
        except (OSError, ValueError) as exc:
            raise ValidationError(
                f"Cannot read model registry at {self.path}; it was left unchanged. "
                "Restore a valid backup, or rename the damaged file and rescan installed models.",
                details={"registry_path": str(self.path), "reason": str(exc)},
            ) from exc

    def _candidates(self) -> list[tuple[str, str, bool]]:
        candidates = [
            (self.settings.model_reference, "model", True),
            (self.settings.vae_reference, "vae", True),
            (self.settings.vae_legacy_reference, "vae", False),
        ]
        roots = {self.settings.models_path}
        configured = Path(self.settings.model_reference)
        if configured.is_dir():
            roots.add(configured.parent)
        directories: set[Path] = set()
        for root in roots:
            if root.is_dir():
                directories.update(root.iterdir())
                if (root / "hub").is_dir():
                    directories.update((root / "hub").iterdir())
        for directory in sorted(directories):
            if re.fullmatch(r"\.model_[0-9a-f]{24}\.deleting", directory.name):
                continue
            if not directory.is_dir():
                continue
            if (directory / "studio-model.json").is_file():
                try:
                    from .model_metadata import read_model_metadata
                    role = read_model_metadata(str(directory)).get("role", "model")
                except (OSError, ValueError):
                    role = "model"  # retain the corrupt descriptor and its actionable error
                candidates.append((str(directory), role, False))
                continue
            try:
                config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
                kind = config.get("model_type") if isinstance(config, dict) else None
            except (OSError, ValueError):
                continue
            if kind in {"yue2", "yue2_vae"}:
                candidates.append((str(directory), "model" if kind == "yue2" else "vae", False))
        return candidates

    def _upsert(self, document: RegistryDocument, descriptor: ModelMetadata) -> ModelRecord:
        reference = str(Path(descriptor.id).resolve())
        registry_id = _identity(reference, descriptor.role)
        previous = next((item for item in document.entries if item.registry_id == registry_id), None)
        if previous and previous.deletion_status == "deleting":
            return previous
        if previous:
            descriptor = self._validated(descriptor.model_copy(update={"registry_id": previous.registry_id}))
        facts = {name: getattr(descriptor, name) for name in ModelFacts.model_fields}
        aliases = sorted({reference, descriptor.id, *(previous.aliases if previous else [])})
        if previous:
            # Preserve known provenance/size when files or metadata disappear.
            if descriptor.validation_status == "failed" or (
                previous.format == "gguf" and not (Path(descriptor.id) / "studio-model.json").is_file()
            ):
                facts = {name: getattr(previous, name) for name in ModelFacts.model_fields}
            else:
                facts = {name: value if value is not None else getattr(previous, name) for name, value in facts.items()}
                if descriptor.revision is not None:
                    facts["commit_hash"] = descriptor.commit_hash
                if previous.huggingface_repo and not descriptor.huggingface_repo:
                    facts["source"] = previous.source
            if aliases == previous.aliases and all(getattr(previous, name) == value for name, value in facts.items()):
                return previous
        now = utcnow()
        record = ModelRecord(**facts, registry_id=registry_id, reference=reference,
                             role=descriptor.role, aliases=aliases,
                             created_at=previous.created_at if previous else now, updated_at=now)
        if previous:
            document.entries[document.entries.index(previous)] = record
        else:
            document.entries.append(record)
        return record

    @staticmethod
    def _attach(descriptor: ModelMetadata, record: ModelRecord) -> ModelMetadata:
        updates = {name: getattr(record, name) for name in ModelFacts.model_fields}
        updates.update(registry_id=record.registry_id, aliases=record.aliases,
                       created_at=record.created_at, updated_at=record.updated_at,
                       registration_status="registered")
        if record.format == "gguf" and not (Path(descriptor.id) / "studio-model.json").is_file():
            updates.update(download_status="downloaded" if (Path(descriptor.id) / record.filename).is_file() else "missing",
                           files_complete=False, inference_status="files_missing",
                           problem="The GGUF installation is missing studio-model.json; restore its installation metadata.")
        if record.deletion_status == "deleting":
            updates.update(deletion_status="deleting", inference_status="files_missing", files_complete=False,
                           problem="Model deletion is incomplete; inspect it and retry cleanup.")
        return descriptor.model_copy(update=updates)

    def get(self, registry_id: str) -> ModelRecord:
        with file_lock(self.lock_path):
            return self._find(self._read(), registry_id)

    def describe(self, reference: str, role: Literal["model", "vae"] = "model") -> ModelMetadata:
        """Apply persisted validation to a direct worker reference without scanning.

        Legacy paths with no registry/report keep their existing file preflight.
        A known stale, failed or incompatible report cannot be bypassed by using
        a path instead of a registry ID.
        """
        entry = describe_model_files(reference, role)
        with file_lock(self.lock_path):
            identity = _identity(str(Path(reference).resolve()), role)
            record = next((r for r in self._read().entries if r.registry_id == identity), None)
            return self._validated(self._attach(entry, record)) if record else entry

    @staticmethod
    def _find(document: RegistryDocument, registry_id: str) -> ModelRecord:
        record = next((item for item in document.entries if item.registry_id == registry_id), None)
        if record is None:
            raise NotFoundError("Model registry entry not found. Refresh the installed model list.")
        return record

    def validation_path(self, registry_id: str) -> Path:
        # All callers first obtain a validated registry record; never accept arbitrary IDs as paths.
        self.get(registry_id)
        return self.store.root / "model-validations" / f"{registry_id}.json"

    def save_validation(self, report: ValidationReport) -> None:
        with file_lock(self.lock_path):
            document = self._read()
            record = self._find(document, report.registry_id)
            if record.deletion_status != "active":
                raise ValidationError("This model is being deleted; validation cannot be saved.")
            if report.validation_status == "validated":
                for name, value in report.facts.items():
                    if name in ModelFacts.model_fields:
                        setattr(record, name, value)
                record.updated_at = utcnow()
                write_json_atomic(self.path, document.model_dump(mode="json"))
            write_json_atomic(self.store.root / "model-validations" / f"{record.registry_id}.json", report.model_dump(mode="json"))

    def _validated(self, entry: ModelMetadata) -> ModelMetadata:
        if not entry.registry_id or entry.deletion_status == "deleting":
            return entry
        path = self.store.root / "model-validations" / f"{entry.registry_id}.json"
        if not path.is_file():
            return entry
        try:
            report = ValidationReport.model_validate_json(path.read_text(encoding="utf-8"))
            if report.registry_id != entry.registry_id:
                raise ValueError("Validation report identity mismatch.")
            if report.files != validation_files(entry):
                raise ValueError("Validation report file list mismatch.")
            if file_fingerprint(Path(entry.id), report.files) != report.fingerprint:
                changes = {"checksum_sha256": None}
                if entry.files_complete and entry.validation_status != "failed":
                    changes.update(inference_status="unknown", problem="Model files changed since validation; validate this installation again.")
                    changes.update(parameter_count=None, tensor_element_count=None, precision=None, quantization=None)
                return entry.model_copy(update=changes)
            if report.validation_status == "validated":
                ModelFacts.model_validate({**{key: getattr(entry, key) for key in ModelFacts.model_fields},
                                          **{key: value for key, value in report.facts.items() if key in ModelFacts.model_fields}})
        except (OSError, ValueError) as exc:
            return entry.model_copy(update={"validation_status": "failed", "inference_status": "validation_failed",
                                            "problem": f"Cannot read validation report; validate this model again: {exc}"})
        updates = {"validation_status": report.validation_status}
        if report.validation_status == "validated":
            updates.update({key: value for key, value in report.facts.items() if key in ModelFacts.model_fields})
        else:
            updates.update(parameter_count=None, tensor_element_count=None, precision=None, quantization=None, checksum_sha256=None)
        if report.validation_status == "failed":
            updates.update(inference_status="validation_failed", problem=report.problem, checksum_sha256=None)
        elif report.compatibility_status != "supported":
            updates.update(compatibility_status=report.compatibility_status,
                           inference_status="incompatible" if report.compatibility_status == "incompatible" else "unknown",
                           problem=report.problem)
        return entry.model_copy(update=updates)

    def register(self, reference: str, role: Literal["model", "vae"] = "model") -> ModelMetadata:
        """Record a completed download without claiming validation or loading."""
        with file_lock(self.lock_path):
            document = self._read()
            before = document.model_dump(mode="json")
            descriptor = describe_model_files(str(Path(reference).absolute()), role)
            if not descriptor.is_local:
                raise ValidationError(f"Cannot register a missing model directory: {reference}")
            record = self._upsert(document, descriptor)
            if document.model_dump(mode="json") != before:
                write_json_atomic(self.path, document.model_dump(mode="json"))
            return self._attach(descriptor, record)

    def install_verified(self, reference: str, report: ValidationReport, *, staging: Path | None = None,
                         role: Literal["model", "vae"] = "model") -> ModelMetadata:
        """Publish complete content and its validation under the inventory lock.

        The caller holds the destination's exclusive file lease. A same-volume
        directory rename exposes all files together; registration failure moves
        a new installation back to private staging for a safe retry.
        """
        destination = Path(reference).absolute()
        with file_lock(self.lock_path):
            document = self._read()  # fail before publishing if the registry is damaged
            if staging is not None and destination.exists():
                raise ValidationError("An installation already exists at the download destination; refresh and retry.")
            moved = False
            try:
                if staging is not None:
                    staging.rename(destination)
                    moved = True
                report.registry_id = _identity(str(destination.resolve()), role)
                if file_fingerprint(destination, report.files) != report.fingerprint:
                    raise ValidationError("Downloaded files changed after verification; retry the download.")
                write_json_atomic(self.store.root / "model-validations" / f"{report.registry_id}.json", report.model_dump(mode="json"))
                descriptor = self._validated(describe_model_files(str(destination), role).model_copy(
                    update={"registry_id": report.registry_id}))
                record = self._upsert(document, descriptor)
                write_json_atomic(self.path, document.model_dump(mode="json"))
                return self._validated(self._attach(descriptor, record))
            except Exception:
                if moved:
                    destination.rename(staging)
                raise

    def inventory(self) -> list[ModelMetadata]:
        """Idempotently import legacy directories, then refresh all known paths."""
        # ponytail: one registry lock; split by installation only if scans contend.
        with file_lock(self.lock_path):
            document = self._read()
            before = document.model_dump(mode="json")
            entries: list[ModelMetadata] = []
            seen: set[str] = set()
            for reference, role, is_default in self._candidates():
                descriptor = describe_model_files(reference, role, is_default=is_default)
                if descriptor.is_local:
                    record = self._upsert(document, descriptor)
                    descriptor = self._attach(descriptor, record)
                key = descriptor.registry_id or descriptor.id
                if key not in seen:
                    seen.add(key)
                    entries.append(descriptor)
            # Registrations outside scan roots, and removed installations, remain visible.
            for record in list(document.entries):
                if record.registry_id in seen:
                    continue
                descriptor = describe_model_files(record.reference, record.role)
                if descriptor.is_local:
                    record = self._upsert(document, descriptor)
                entries.append(self._attach(descriptor, record))
            if document.model_dump(mode="json") != before:
                write_json_atomic(self.path, document.model_dump(mode="json"))
            records = {record.registry_id: record for record in document.entries}
            return [self._validated(self._attach(entry, records[entry.registry_id])) if entry.registry_id else entry for entry in entries]
