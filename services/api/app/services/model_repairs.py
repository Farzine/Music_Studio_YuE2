"""Repair installed Hub packages through the existing download queue and leases."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from yue2_studio_core.errors import ConflictError, ValidationError
from yue2_studio_core.model_download import DOWNLOAD_DISK_RESERVE_BYTES
from yue2_studio_core.model_metadata import model_required_files


def repair_preview(downloads, registry_id: str) -> dict:
    from app.services.models import ModelService
    record = downloads.registry.get(registry_id)
    if not record.huggingface_repo or not record.filename:
        raise ValidationError("No Hugging Face source is recorded. Inspect the source repository on Download Model first.")
    commit = record.commit_hash or record.revision
    if not commit or not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
        raise ValidationError("Repair requires the original immutable commit. Inspect the repository and download a verified installation.")
    deletion = ModelService(downloads.registry).preview(registry_id)
    if not deletion["can_delete"]:
        raise ConflictError("Cannot repair this installation: " + " ".join(deletion["blockers"]))
    root = Path(record.reference)
    downloads._check_tree(root)
    inspection = downloads.hub.inspect(record.huggingface_repo, commit)
    # Preserve optional repository content previously requested, including when
    # that content has since disappeared from the local installation.
    names = set(model_required_files(record.filename))
    for job in downloads.list():
        if (job.get("destination") or job.get("path")) == record.reference:
            names.update(f["name"] for f in job.get("files", []))
    plan = downloads.hub.preview(inspection, record.filename, mode="selected", selected_files=sorted(names))
    repair_files = []
    for file in plan["files"]:
        try:
            downloads._verify_file(root, dict(file))
        except (ValidationError, OSError):
            repair_files.append(file)
    required = sum(f["bytes"] or 0 for f in repair_files)
    parent = root
    while not parent.exists():
        parent = parent.parent
    free = shutil.disk_usage(parent).free
    token = hashlib.sha256(json.dumps([deletion["confirmation_token"], commit, plan["files"]], sort_keys=True).encode()).hexdigest()
    return {"registry_id": registry_id, "repo_id": record.huggingface_repo, "revision": commit,
            "filename": record.filename, "role": record.role, "destination": record.reference,
            "files": plan["files"], "repair_files": repair_files,
            "download_bytes": None if any(f["bytes"] is None for f in repair_files) else required,
            "free_bytes": free, "safety_margin_bytes": DOWNLOAD_DISK_RESERVE_BYTES,
            "can_repair": required + DOWNLOAD_DISK_RESERVE_BYTES <= free,
            "confirmation_token": token}
