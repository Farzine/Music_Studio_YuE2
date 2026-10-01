"""Persistent atomic Hugging Face downloads using the existing SDK and registry."""
from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import time
from pathlib import Path

from huggingface_hub.utils import HfHubHTTPError
from requests.exceptions import RequestException

from app.services.huggingface import HuggingFaceService, hub_error, installation_path, validate_source
from app.services.huggingface_transfer import download_file
from yue2_studio_core.errors import ConflictError, StudioError, ValidationError
from yue2_studio_core.ids import new_id
from yue2_studio_core.model_download import ACTIVE_DOWNLOAD_STATES, DOWNLOAD_DISK_RESERVE_BYTES, download_progress, transition_download
from yue2_studio_core.model_metadata import describe_model_files
from yue2_studio_core.model_registry import ModelRegistry
from yue2_studio_core.model_files import model_file_leases
from yue2_studio_core.model_validator import UnsupportedEncoding, gguf_metadata, safetensors_metadata, validate_installation
from yue2_studio_core.models import utcnow
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store, file_lock, write_json_atomic

logger = logging.getLogger(__name__)


def _process_start(pid: int):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _owner_alive(job: dict) -> bool:
    if job.get("hostname", socket.gethostname()) != socket.gethostname():
        return True  # shared storage does not establish a remote process's death
    pid = job.get("pid")
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except PermissionError:
        return True
    start = _process_start(pid)
    return not job.get("process_start") or start is None or job["process_start"] == start


class ModelDownloads:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings, self.store = settings, store
        self.registry = ModelRegistry(settings, store)
        self.hub = HuggingFaceService(settings)
        self.root = store.root / "model-downloads"
        self.root.mkdir(parents=True, exist_ok=True)

    def browse(self, repo_id: str, revision: str | None = None) -> dict:
        result = self.hub.inspect(repo_id, revision)
        return {"repo_id": repo_id, "revision": result["revision"],
                "files": [{"name": f["name"], "bytes": f["bytes"]} for f in result["files"]
                          if f["extension"] in {".gguf", ".safetensors"}]}

    def _path(self, download_id: str) -> Path:
        if not re.fullmatch(r"mdl_[A-Za-z0-9_-]+", download_id):
            raise ValidationError("Invalid download ID.")
        return self.root / f"{download_id}.json"

    def _write(self, job: dict) -> None:
        job.update(download_progress(job), updated_at=utcnow().isoformat())
        write_json_atomic(self._path(job["id"]), job)

    def _stage(self, job: dict) -> Path:
        hub = self.settings.models_path.resolve() / "hub"
        if not hub.resolve().is_relative_to(self.settings.models_path.resolve()):
            raise ValidationError("Model hub storage points outside MODELS_DIR; restore its directory before downloading.")
        root = hub / ".downloads"
        path = root / job["id"]
        if root.is_symlink() or path.is_symlink():
            raise ValidationError("Download staging points to a symlink; restore the staging directory before retrying.")
        return path

    def _load(self, download_id: str) -> dict:
        path = self._path(download_id)
        if not path.is_file():
            raise ValidationError("Model download not found.")
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item["id"] != download_id or item["status"] not in ACTIVE_DOWNLOAD_STATES | {"complete", "failed"}:
                raise ValueError("Invalid job identity/state")
            validate_source(item["repo_id"], item["filename"], item["revision"])
            for f in item.get("files", []):
                validate_source(item["repo_id"], f["name"])
                for key in ("bytes", "downloaded_bytes"):
                    value = f.get(key)
                    if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
                        raise ValueError("Invalid persisted byte count")
                if f.get("checksum_sha256") and not re.fullmatch(r"[a-fA-F0-9]{64}", f["checksum_sha256"]):
                    raise ValueError("Invalid persisted SHA256")
            if len({f["name"] for f in item.get("files", [])}) != len(item.get("files", [])):
                raise ValueError("Duplicate persisted file selection")
        except (ValueError, TypeError, KeyError) as exc:
            raise ValidationError(f"Download record {download_id} is damaged; restore it before starting more downloads.") from exc
        return item

    def _busy_check(self) -> None:
        # ponytail: one active transfer across API processes; parallel downloads
        # require an explicit storage/network admission policy, not more threads.
        if any(j["status"] in ACTIVE_DOWNLOAD_STATES for j in self.list()):
            raise ConflictError("A model download is already active. Wait for it to finish before starting another.")

    def start(self, repo_id: str, filename: str, revision: str | None,
              *, mode: str = "single", selected_files: list[str] | None = None) -> dict:
        validate_source(repo_id, filename, revision)
        with file_lock(self.root / ".admission.lock"):
            self._busy_check()
            inspection = self.hub.inspect(repo_id, revision)
            plan = self.hub.preview(inspection, filename, mode=mode, selected_files=selected_files)
            if not plan["can_download"]:
                raise ValidationError("Insufficient disk space for selected content plus 1 GiB of headroom.")
            now = utcnow().isoformat()
            job = {
                "schema_version": 2, "id": new_id("mdl"), "repo_id": repo_id, "filename": filename,
                "revision": plan["revision"], "requested_revision": revision or "main", "mode": mode,
                "selection_identity": plan["selection_identity"],
                "files": [{**f, "downloaded_bytes": 0} for f in plan["files"]],
                "status": "queued", "error": None, "path": None, "destination": plan["destination"],
                "completed_files": 0, "total_files": len(plan["files"]), "current_file": None,
                "pid": os.getpid(), "hostname": socket.gethostname(), "process_start": _process_start(os.getpid()),
                "attempt": 1, "created_at": now, "updated_at": now, "bytes_per_second": None,
                "validation_status": "not_validated", "inference_status": "unknown", "registry_id": None,
                "force_download_files": [], "partial_bytes": 0,
            }
            self._write(job)
            return job

    def get(self, download_id: str) -> dict:
        item = self._load(download_id)
        # v2 running jobs hold this lease through every write. A free lease can
        # recover an abandoned thread even if the API process itself is alive.
        probe = item["status"] in ACTIVE_DOWNLOAD_STATES and (
            not _owner_alive(item) or (item.get("schema_version") == 2 and item["status"] != "queued"))
        if probe:
            try:
                with file_lock(self.root / f".{download_id}.run.lock", blocking=False):
                    item = self._load(download_id)
                    if item["status"] in ACTIVE_DOWNLOAD_STATES and (
                            not _owner_alive(item) or (item.get("schema_version") == 2 and item["status"] != "queued")):
                        transition_download(item, "failed")
                        item.update(error="Download was interrupted; Retry resumes private staging, or remove its partial files.", current_file=None)
                        self._write(item)
            except ConflictError:
                pass  # a live invocation still owns the transfer
        return {**item, **download_progress(item)} if "files" in item else item

    def list(self) -> list[dict]:
        return [self.get(path.stem) for path in sorted(self.root.glob("mdl_*.json"))]

    def retry(self, download_id: str) -> dict:
        self.get(download_id)  # recover a dead owner before taking its run lease
        with file_lock(self.root / ".admission.lock"), file_lock(self.root / f".{self._path(download_id).stem}.run.lock", blocking=False):
            self._busy_check()
            job = self.get(download_id)
            if job["status"] != "failed":
                raise ConflictError("Only failed/interrupted downloads can be retried.")
            # Legacy interrupted records resolve their original branch once; all
            # new attempts retain the immutable commit and exact selected files.
            if not job.get("files"):
                inspection = self.hub.inspect(job["repo_id"], job["revision"])
                plan = self.hub.preview(inspection, job["filename"])
                job.update(revision=plan["revision"], mode="single", destination=plan["destination"],
                           selection_identity=plan["selection_identity"],
                           files=[{**f, "downloaded_bytes": 0} for f in plan["files"]])
            transition_download(job, "queued")
            job.update(pid=os.getpid(), hostname=socket.gethostname(), process_start=_process_start(os.getpid()),
                       error=None, attempt=job.get("attempt", 1) + 1, path=None, current_file=None,
                       completed_files=0, bytes_per_second=None, registry_id=None,
                       validation_status="not_validated", inference_status="unknown",
                       files=[{**f, "sha256": None, "checksum_verified": False} for f in job["files"]])
            self._write(job)
            return job

    def cleanup(self, download_id: str) -> dict:
        self.get(download_id)
        with file_lock(self.root / f".{self._path(download_id).stem}.run.lock", blocking=False):
            job = self.get(download_id)
            if job["status"] != "failed":
                raise ConflictError("Only failed downloads can have their private partial files removed.")
            stage = self._stage(job)
            if stage.exists():
                shutil.rmtree(stage)
            job.update(partial_bytes=0, files=[{**f, "downloaded_bytes": 0, "sha256": None, "checksum_verified": False} for f in job.get("files", [])], bytes_per_second=None)
            self._write(job)
            return job

    def _check_tree(self, root: Path) -> None:
        if root.is_symlink() or any(p.is_symlink() for p in root.rglob("*")):
            raise ValidationError("Download content contains a symlink; remove private partial files and retry.")

    def _verify_file(self, root: Path, file: dict) -> None:
        path = root / file["name"]
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValidationError(f"Downloaded file {file['name']} is missing or outside its installation.")
        size = path.stat().st_size
        if file["bytes"] is not None and size != file["bytes"]:
            raise ValidationError(f"Size mismatch for {file['name']}; retry to download this file again.")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024**2), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if file.get("checksum_sha256") and file["checksum_sha256"].lower() != actual:
            raise ValidationError(f"SHA256 mismatch for {file['name']}; retry to download this file again.")
        file.update(bytes=size, downloaded_bytes=size, sha256=actual, checksum_verified=bool(file.get("checksum_sha256")))
        try:
            if path.suffix.lower() == ".gguf":
                gguf_metadata(path)
            elif path.suffix.lower() == ".safetensors":
                safetensors_metadata(path)
        except UnsupportedEncoding:
            pass  # retained as needs-validation by the shared package reader
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Invalid model structure in {file['name']}: {exc}") from exc

    def _run(self, job: dict) -> None:
        if job["status"] != "queued":
            return
        validate_source(job["repo_id"], job["filename"], job["revision"])
        if not re.fullmatch(r"[0-9a-fA-F]{40}", job["revision"]):
            raise ValidationError("An immutable download commit is required; inspect the repository and start a new download.")
        # Rebuild the plan from persisted selected metadata; never trust a saved
        # filesystem destination, mutable branch or arbitrary cleanup path.
        inspection = {"repo_id": job["repo_id"], "revision": job["revision"], "requested_revision": job.get("requested_revision", job["revision"]),
                      "files": job["files"], "candidates": [{"model": {"filename": job["filename"]}}], "warnings": []}
        plan = self.hub.preview(inspection, job["filename"], mode="selected", selected_files=[f["name"] for f in job["files"]])
        identity = job.get("selection_identity", "")
        if identity and identity != "\n".join(sorted(f["name"] for f in job["files"])):
            raise ValidationError("Download selection changed; inspect the repository and start a new download.")
        destination = installation_path(self.settings, job["repo_id"], job["revision"], job["filename"], extra_identity=identity)
        if job.get("destination") != str(destination):
            raise ValidationError("Download destination no longer matches its original selection; inspect the repository and start a new download.")
        stage = self._stage(job)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with model_file_leases(self.store, [str(destination)], shared=False, blocking=False):
            root = destination if destination.exists() else stage
            self._check_tree(root)
            allocated = sum(p.stat().st_blocks * 512 for p in root.rglob("*") if p.is_file()) if root.exists() else 0
            required = max(0, plan["known_bytes"] - allocated)
            if required + DOWNLOAD_DISK_RESERVE_BYTES > shutil.disk_usage(destination.parent).free:
                raise ValidationError("Insufficient free disk space for the remaining content and 1 GiB of headroom.")
            if root == destination:
                try:
                    metadata = json.loads((root / "studio-model.json").read_text())
                except (OSError, ValueError, RecursionError) as exc:
                    raise ConflictError("The destination has missing/damaged installation metadata. Inspect it and delete it explicitly before retrying; its files were preserved.") from exc
                if any(metadata.get(key) != value for key, value in {"repo_id": job["repo_id"], "revision": job["revision"], "filename": job["filename"]}.items()):
                    raise ConflictError("The destination contains a different installation. Inspect/delete it explicitly before downloading here.")
            transition_download(job, "downloading")
            self._write(job)
            for file in job["files"]:
                validate_source(job["repo_id"], file["name"])
                job["current_file"] = file["name"]
                self._write(job)
                if root == stage:
                    stage.mkdir(parents=True, exist_ok=True)
                    last_time, last_bytes, last_write = time.monotonic(), None, 0.0
                    def progress(count, total):
                        nonlocal last_time, last_bytes, last_write
                        if total is not None:
                            if file["bytes"] is not None and file["bytes"] != total:
                                raise ValidationError(f"Hugging Face transfer size changed for {file['name']}; inspect the repository again.")
                            file["bytes"] = total
                            if last_bytes is None:
                                known = sum(f["bytes"] or 0 for f in job["files"])
                                allocated = sum(p.stat().st_blocks * 512 for p in stage.rglob("*") if p.is_file())
                                if max(0, known - allocated) + DOWNLOAD_DISK_RESERVE_BYTES > shutil.disk_usage(stage).free:
                                    raise ValidationError("Insufficient disk space for the transfer's newly resolved size; free storage and Retry.")
                        file["downloaded_bytes"] = count
                        now = time.monotonic()
                        if last_bytes is not None and count >= last_bytes and now > last_time:
                            job["bytes_per_second"] = (count - last_bytes) / (now - last_time)
                        else:
                            job["bytes_per_second"] = None  # resumed/cached bytes are not network speed
                        if now - last_write >= 0.25:
                            self._write(job)
                            last_write, last_time, last_bytes = now, now, count
                    download_file(job["repo_id"], file["name"], revision=job["revision"], local_dir=stage,
                                  callback=progress, force_download=file["name"] in job.get("force_download_files", []))
                # SDK cache hits have no transfer callback. Count observed final
                # bytes without inventing a rate or trusting metadata alone.
                file["downloaded_bytes"] = (root / file["name"]).stat().st_size
                if file["bytes"] is None:
                    file["bytes"] = file["downloaded_bytes"]
                job["completed_files"] += 1
                job["bytes_per_second"] = None
                self._write(job)
            transition_download(job, "verifying")
            self._write(job)
            for file in job["files"]:
                job["current_file"] = file["name"]
                self._write(job)
                try:
                    self._verify_file(root, file)
                except ValidationError:
                    if root == stage:
                        job["force_download_files"] = sorted({*job.get("force_download_files", []), file["name"]})
                    else:
                        raise ConflictError(f"Existing installation has invalid {file['name']}. Inspect/delete it explicitly before retrying; it was left unchanged.")
                    raise
            if root == stage:
                write_json_atomic(root / "studio-model.json", {"repo_id": job["repo_id"], "revision": job["revision"], "filename": job["filename"]})
            entry = describe_model_files(str(root), "model").model_copy(update={"registry_id": "pending_download"})
            report = validate_installation(entry, verify_checksum=entry.files_complete)
            # Missing sidecars / an unsupported architecture can be managed as
            # complete downloads. Corrupt structures in complete packages cannot.
            if report.validation_status == "failed" and entry.files_complete:
                job["force_download_files"] = [f["name"] for f in job["files"]]
                raise ValidationError(report.problem or "Downloaded model failed structural validation.")
            transition_download(job, "registering")
            job.update(validation_status=report.validation_status, current_file=None)
            self._write(job)
            installed = self.registry.install_verified(str(destination), report, staging=stage if root == stage else None)
            transition_download(job, "complete")
            job.update(path=str(destination), registry_id=installed.registry_id, validation_status=installed.validation_status,
                       inference_status=installed.inference_status, current_file=None, partial_bytes=0, force_download_files=[])
            if stage.exists():
                try:
                    shutil.rmtree(stage)
                except OSError:
                    logger.warning("Completed download's private staging cleanup failed", exc_info=True)
            self._write(job)

    def run(self, download_id: str) -> None:
        try:
            with file_lock(self.root / f".{self._path(download_id).stem}.run.lock", blocking=False):
                job = self.get(download_id)
                if job["status"] != "queued":
                    return
                try:
                    self._run(job)
                except Exception as exc:
                    failed_stage = job["status"]
                    if job["status"] in ACTIVE_DOWNLOAD_STATES:
                        transition_download(job, "failed")
                    if isinstance(exc, (HfHubHTTPError, RequestException)):
                        message = hub_error(exc, job["repo_id"], job["revision"]).message
                    elif isinstance(exc, StudioError):
                        message = exc.message
                    elif isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                        message = "Disk became full during download. Free storage and Retry or remove private partial files."
                    else:
                        logger.exception("Model download failed during %s", failed_stage)
                        message = f"Download failed during {failed_stage}; check API logs, then Retry. Installed models were preserved."
                    partial = None
                    try:
                        stage = self._stage(job)
                        partial = sum(p.stat().st_blocks * 512 for p in stage.rglob("*") if p.is_file() and not p.is_symlink()) if stage.exists() else 0
                    except (OSError, StudioError):
                        pass
                    job.update(error=message, current_file=None, partial_bytes=partial)
                    self._write(job)
        except ConflictError:
            return  # another invocation owns this same job; never fail its transfer

    def shutdown(self) -> None:
        """Fail abandoned requests owned by this API; never mutate a live transfer."""
        with file_lock(self.root / ".admission.lock"):
            for path in self.root.glob("mdl_*.json"):
                job = self._load(path.stem)
                if job.get("pid") != os.getpid() or job.get("hostname") != socket.gethostname():
                    continue
                try:
                    with file_lock(self.root / f".{path.stem}.run.lock", blocking=False):
                        job = self._load(path.stem)
                        if job["status"] in ACTIVE_DOWNLOAD_STATES:
                            transition_download(job, "failed")
                            job.update(error="API stopped before this download finished; Retry resumes private staging.", current_file=None)
                            self._write(job)
                except ConflictError:
                    continue  # ASGI waits for ordinary BackgroundTasks; a live
                    # thread after a forced timeout still owns its atomic staging.
