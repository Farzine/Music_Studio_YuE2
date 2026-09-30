"""Inspect, validate and delete installations; all GPU operations stay in worker."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

from yue2_studio_core.errors import ConflictError, ValidationError
from yue2_studio_core.model_files import model_file_leases
from yue2_studio_core.model_metadata import describe_model_files, resolve_model_reference, resolve_vae_reference
from yue2_studio_core.model_registry import ModelRecord, ModelRegistry
from yue2_studio_core.model_validator import validate_installation
from yue2_studio_core.models import GenerationJob, utcnow
from yue2_studio_core.settings import repo_root
from yue2_studio_core.store import file_lock, write_json_atomic


class ModelService:
    def __init__(self, registry: ModelRegistry) -> None:
        self.registry, self.store, self.settings = registry, registry.store, registry.settings

    def inspect(self, registry_id: str) -> dict:
        record = self.registry.get(registry_id)
        entry = next(item for item in self.registry.inventory() if item.registry_id == record.registry_id)
        path = self.registry.validation_path(registry_id)
        try:
            validation = json.loads(path.read_text()) if path.is_file() else None
        except (OSError, ValueError):
            validation = {"error": "Stored validation report is unreadable; validate this model again."}
        return {"model": entry.model_dump(mode="json"), "validation": validation,
                "deletion": self.preview(registry_id)}

    def validate(self, registry_id: str, *, verify_checksum: bool = False) -> dict:
        record = self.registry.get(registry_id)
        with model_file_leases(self.store, [record.reference]):
            entry = self.registry._attach(describe_model_files(record.reference, record.role), record)
            report = validate_installation(entry, verify_checksum=verify_checksum)
            self.registry.save_validation(report)
        return {"validation": report.model_dump(mode="json")}

    def _blockers(self, record: ModelRecord) -> list[str]:
        blockers = []
        target = Path(record.reference)
        root = self.settings.models_path.resolve()
        if target == root or not target.is_relative_to(root):
            blockers.append("This installation is outside the managed model directory; remove its files manually.")
        protected = [repo_root(), self.store.root.resolve(), self.settings.configs_path.resolve(),
                     *(repo_root() / name for name in (".git", ".agents", ".codex", ".venv-api", ".venv-yue2"))]
        if any(path == target or path.is_relative_to(target) for path in protected):
            blockers.append("This directory contains application data, configuration or runtime files and cannot be deleted as a model.")
        if target.resolve() != target:
            blockers.append("The installation path now points elsewhere. Restore the original path before deleting.")
        # Fail closed: Store.iter_jobs deliberately skips malformed records for UI queries.
        for path in self.store.jobs_dir.glob("*.json"):
            try:
                job = GenerationJob.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                blockers.append(f"Task record {path.name} is unreadable; repair it before deleting model files.")
                continue
            if job.status.is_terminal:
                continue
            references = [resolve_model_reference(job.config.model.checkpoint, self.settings),
                          resolve_vae_reference(job.config.model.vae, self.settings)]
            if any(Path(reference).resolve().is_relative_to(target) or target.is_relative_to(Path(reference).resolve()) for reference in references):
                blockers.append(f"Task {job.id} ({job.status.value}) requires this installation; finish or cancel it first.")
        for other in self.registry._read().entries:
            path = Path(other.reference)
            if other.registry_id != record.registry_id and (path.is_relative_to(target) or target.is_relative_to(path)):
                blockers.append(f"This directory overlaps registered installation {other.registry_id}; shared files cannot be deleted.")
        # Protect residency reported by workers started before file leases were implemented.
        for path in (self.store.root / "worker").glob("*.json"):
            try:
                worker = json.loads(path.read_text())
                pid = worker.get("pid")
                if type(pid) is not int or pid <= 0:
                    blockers.append(f"Worker residency cannot be established from {path.name}; stop or repair that worker first.")
                    continue
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    pass
                model = worker.get("model") or {}
                if model.get("loaded") and any(Path(ref).resolve() == target for ref in (model.get("model"), model.get("vae")) if ref):
                    blockers.append(f"Worker {worker.get('worker_id', path.stem)} still reports this model/VAE loaded; unload or stop it first.")
            except (OSError, ValueError, TypeError, AttributeError):
                blockers.append(f"Worker record {path.name} is unreadable; stop or repair that worker before deleting.")
        return blockers

    def _plan(self, record: ModelRecord) -> dict:
        original = Path(record.reference)
        trash = Path(record.trash_path) if record.trash_path else None
        directory = trash if trash and trash.exists() else original
        if trash and trash.exists() and original.exists():
            raise ConflictError("Both original and deletion staging directories exist; inspect them before cleanup.")
        files, allocated = [], 0
        if directory.is_dir():
            root_stat = directory.lstat()
            if stat.S_ISLNK(root_stat.st_mode):
                raise ConflictError("The deletion directory is a symlink; restore its original directory first.")
            mount_file = Path("/proc/self/mountinfo")
            mounts = set()
            if mount_file.is_file():
                for line in mount_file.read_text().splitlines():
                    mount = line.split()[4]
                    for escaped, character in ((r"\040", " "), (r"\011", "\t"), (r"\012", "\n"), (r"\134", "\\")):
                        mount = mount.replace(escaped, character)
                    mounts.add(mount)
            if str(directory) in mounts or os.path.ismount(directory):
                raise ConflictError("The installation is a mount point; unmount or remove its files manually.")
            def on_error(error):
                raise ConflictError(f"Cannot preview all model files: {error}. Fix directory permissions before deleting.")
            for parent, dirs, names in os.walk(directory, followlinks=False, onerror=on_error):
                for name in sorted(dirs + names):
                    path = Path(parent) / name
                    info = path.lstat()
                    if str(path) in mounts or info.st_dev != root_stat.st_dev:
                        raise ConflictError("The installation contains mounted files/directories; unmount them before deleting.")
                    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                        raise ConflictError("Model directory contains a special file; remove it manually before deletion.")
                    files.append({"path": str(path.relative_to(directory)), "bytes": info.st_size,
                                  "mode": info.st_mode, "inode": info.st_ino, "device": info.st_dev,
                                  "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
                                  "links": info.st_nlink})
                    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        allocated += info.st_blocks * 512
            identity = [root_stat.st_dev, root_stat.st_ino, root_stat.st_mtime_ns, root_stat.st_ctime_ns]
        elif directory.exists() or directory.is_symlink():
            raise ConflictError("The registered installation is no longer a directory.")
        else:
            identity = None
        plan = {"registry_id": record.registry_id, "path": str(directory), "original_path": str(original),
                "directory_identity": identity, "files": sorted(files, key=lambda item: item["path"]),
                "estimated_reclaimed_bytes": allocated, "deletion_status": record.deletion_status}
        plan["confirmation_token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        return plan

    def preview(self, registry_id: str) -> dict:
        record = self.registry.get(registry_id)
        with file_lock(self.registry.lock_path):
            blockers = self._blockers(record)
        try:
            with model_file_leases(self.store, [record.reference], shared=False, blocking=False):
                pass
        except ConflictError as exc:
            blockers.append(str(exc))
        return {**self._plan(record), "blockers": blockers, "can_delete": not blockers,
                "warning": "This permanently removes the listed installation and partial files. Disk space reclaimed is an estimate; symlink targets and shared hard links are preserved."}

    def delete(self, registry_id: str, *, confirmation_token: str, confirmed_path: str) -> dict:
        record = self.registry.get(registry_id)
        # Lock order: queue -> file leases -> registry. Admission validates under the queue lock too.
        with self.store.queue_lock(), model_file_leases(self.store, [record.reference], shared=False, blocking=False), file_lock(self.registry.lock_path):
            document = self.registry._read()
            record = self.registry._find(document, registry_id)
            blockers = self._blockers(record)
            if blockers:
                raise ConflictError("Cannot delete this model: " + " ".join(blockers))
            plan = self._plan(record)
            if plan["confirmation_token"] != confirmation_token or plan["path"] != confirmed_path:
                raise ConflictError("The model files or deletion path changed. Inspect the new preview and confirm again.")
            original = Path(record.reference)
            trash = Path(record.trash_path) if record.trash_path else original.with_name(f".{record.registry_id}.deleting")
            if record.deletion_status == "active":
                if trash.exists() or trash.is_symlink():
                    raise ConflictError("A deletion staging path already exists. Inspect it before deleting.")
                record.deletion_status, record.trash_path, record.updated_at = "deleting", str(trash), utcnow()
                write_json_atomic(self.registry.path, document.model_dump(mode="json"))
            try:
                if original.is_dir() and not trash.exists():
                    original.rename(trash)  # Same filesystem; journal already recorded if interrupted.
                if trash.exists():
                    shutil.rmtree(trash)  # Does not follow contained symlinks.
                document.entries.remove(record)
                write_json_atomic(self.registry.path, document.model_dump(mode="json"))
            except OSError as exc:
                return {"deleted": False, "complete": False, "registry_id": registry_id,
                        "error": str(exc), "guidance": "Model deletion is incomplete. Inspect a fresh preview and retry cleanup."}
            validation = self.store.root / "model-validations" / f"{registry_id}.json"
            try:
                validation.unlink(missing_ok=True)
            except OSError:
                pass  # The model registry no longer references this stale report.
            return {"deleted": True, "complete": True, "registry_id": registry_id,
                    "estimated_reclaimed_bytes": plan["estimated_reclaimed_bytes"]}
