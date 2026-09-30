"""Small Hugging Face download registry shared by API restarts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from pathlib import Path, PurePosixPath

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import HFValidationError, validate_repo_id
from yue2_studio_core.errors import ValidationError
from yue2_studio_core.ids import new_id
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store, write_json_atomic

_LOCK = threading.Lock()
_GGUF_COMPANIONS = (
    "yue2-vae-f16.gguf",
    "sidecars/yue2-model-config.json",
    "sidecars/yue2-generation-config.json",
    "sidecars/yue2-qwen.tiktoken",
    "sidecars/yue2-vae-config.json",
)
_NATIVE_COMPANIONS = (
    "config.json", "generation_config.json", "yue2_generation_config.json",
    "weights_manifest.json", "qwen.tiktoken", "modeling_yue2.py",
)


def _validate(repo_id: str, filename: str | None, revision: str | None) -> None:
    try:
        validate_repo_id(repo_id)
    except HFValidationError as exc:
        raise ValidationError(f"Invalid Hugging Face repository ID: {exc}") from exc
    if filename:
        path = PurePosixPath(filename)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in filename.split("/")):
            raise ValidationError("Choose a file inside the model repository.")
    if revision and (not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", revision) or ".." in revision):
        raise ValidationError("Invalid branch, tag or revision.")


class ModelDownloads:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.root = store.root / "model-downloads"
        self.root.mkdir(parents=True, exist_ok=True)

    def browse(self, repo_id: str, revision: str | None = None) -> dict:
        _validate(repo_id, None, revision)
        try:
            info = HfApi().model_info(repo_id, revision=revision, files_metadata=True)
        except Exception as exc:
            raise ValidationError(f"Could not inspect {repo_id}: {exc}") from exc
        files = sorted(
            ({"name": item.rfilename, "bytes": item.size} for item in info.siblings or []
             if item.rfilename.endswith((".gguf", ".safetensors"))),
            key=lambda item: item["name"],
        )
        return {"repo_id": repo_id, "revision": info.sha, "files": files}

    def start(self, repo_id: str, filename: str, revision: str | None) -> dict:
        _validate(repo_id, filename, revision)
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
            companions = _GGUF_COMPANIONS if filename.endswith(".gguf") else _NATIVE_COMPANIONS
            files = [filename, *(name for name in companions if name in names and name != filename)]
            if filename.endswith(".gguf") and not all(name in names for name in _GGUF_COMPANIONS):
                # Other GGUF repositories can still be downloaded, but cannot
                # claim inference support without the YuE2 package files.
                files = [filename]
            digest = hashlib.sha256(f"{repo_id}@{info.sha}/{filename}".encode()).hexdigest()[:12]
            destination = self.settings.models_path / "hub" / f"{repo_id.replace('/', '--')}--{digest}"
            self.settings.models_path.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.settings.models_path).free < sum(
                int(item.size or 0) for item in info.siblings or [] if item.rfilename in files
            ) + 1024**3:
                raise ValueError("Not enough free disk space for this model and 1 GiB of headroom.")
            job.update(revision=info.sha, total_files=len(files))
            write_json_atomic(path, job)
            for name in files:
                job["current_file"] = name
                write_json_atomic(path, job)
                hf_hub_download(repo_id, name, revision=info.sha, local_dir=destination)
                job["completed_files"] += 1
                write_json_atomic(path, job)
            metadata = {"repo_id": repo_id, "revision": info.sha, "filename": filename}
            write_json_atomic(destination / "studio-model.json", metadata)
            job.update(status="complete", path=str(destination), current_file=None)
        except Exception as exc:
            job.update(status="failed", error=str(exc), current_file=None)
        write_json_atomic(path, job)
