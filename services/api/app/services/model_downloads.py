"""Persistent Hugging Face download jobs, registering completed installations."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading

from huggingface_hub import HfApi, hf_hub_download
from yue2_studio_core.errors import ValidationError
from yue2_studio_core.ids import new_id
from app.services.huggingface import HuggingFaceService, default_download_files, installation_path, validate_source
from yue2_studio_core.model_registry import ModelRegistry
from yue2_studio_core.model_files import model_file_leases
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store, write_json_atomic

_LOCK = threading.Lock()


class ModelDownloads:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.registry = ModelRegistry(settings, store)
        self.hub = HuggingFaceService(settings)
        self.root = store.root / "model-downloads"
        self.root.mkdir(parents=True, exist_ok=True)

    def browse(self, repo_id: str, revision: str | None = None) -> dict:
        result = self.hub.inspect(repo_id, revision)
        return {"repo_id": repo_id, "revision": result["revision"],
                "files": [{"name": f["name"], "bytes": f["bytes"]} for f in result["files"]
                          if f["extension"] in {".gguf", ".safetensors"}]}

    def start(self, repo_id: str, filename: str, revision: str | None) -> dict:
        validate_source(repo_id, filename, revision)
        if not filename.endswith((".gguf", ".safetensors")):
            raise ValidationError("Choose a GGUF or safetensors model file.")
        with _LOCK:
            for item in self.list():
                if item["status"] == "downloading":
                    raise ValidationError("A model download is already running.")
            job = {
                "id": new_id("mdl"), "repo_id": repo_id, "filename": filename,
                "revision": revision or "main", "status": "downloading", "error": None,
                "path": None, "completed_files": 0, "total_files": None,
                "current_file": None, "pid": os.getpid(),
            }
            write_json_atomic(self.root / f"{job['id']}.json", job)
            return job

    def get(self, download_id: str) -> dict:
        if not re.fullmatch(r"mdl_[A-Za-z0-9_-]+", download_id):
            raise ValidationError("Invalid download ID.")
        path = self.root / f"{download_id}.json"
        if not path.is_file():
            raise ValidationError("Model download not found.")
        item = json.loads(path.read_text(encoding="utf-8"))
        if item["status"] == "downloading" and item.get("pid") != os.getpid():
            item.update(status="failed", error="Download was interrupted; try again.")
            write_json_atomic(path, item)
        return item

    def list(self) -> list[dict]:
        return [self.get(path.stem) for path in sorted(self.root.glob("mdl_*.json"))]

    def run(self, download_id: str) -> None:
        job = self.get(download_id)
        path = self.root / f"{download_id}.json"
        try:
            repo_id, filename, revision = job["repo_id"], job["filename"], job["revision"]
            info = HfApi().model_info(repo_id, revision=revision, files_metadata=True)
            names = {item.rfilename for item in info.siblings or []}
            if filename not in names:
                raise ValueError(f"{filename} is not in {repo_id}@{revision}.")
            files = default_download_files(filename, names)
            destination = installation_path(self.settings, repo_id, info.sha, filename)
            self.settings.models_path.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.settings.models_path).free < sum(
                int(item.size or 0) for item in info.siblings or [] if item.rfilename in files
            ) + 1024**3:
                raise ValueError("Not enough free disk space for this model and 1 GiB of headroom.")
            job.update(revision=info.sha, total_files=len(files))
            write_json_atomic(path, job)
            with model_file_leases(self.store, [str(destination)], shared=False, blocking=False):
                for name in files:
                    job["current_file"] = name
                    write_json_atomic(path, job)
                    hf_hub_download(repo_id, name, revision=info.sha, local_dir=destination)
                    job["completed_files"] += 1
                    write_json_atomic(path, job)
                metadata = {"repo_id": repo_id, "revision": info.sha, "filename": filename}
                write_json_atomic(destination / "studio-model.json", metadata)
                self.registry.register(str(destination))
            job.update(status="complete", path=str(destination), current_file=None)
        except Exception as exc:
            job.update(status="failed", error=str(exc), current_file=None)
        write_json_atomic(path, job)
