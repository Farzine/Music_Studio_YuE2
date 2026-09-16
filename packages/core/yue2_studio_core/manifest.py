"""Reproducibility manifest.

Every completed generation writes one. It has to be enough on its own to
explain what produced a result: the exact request, the effective configuration,
the weights by hash, the runtime versions and the hardware.
"""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from .constants import MANIFEST_SCHEMA_VERSION
from .models import GenerationJob, utcnow


def identity(value: Any) -> str:
    """Content hash matching ``yue2.storage.identity`` so ids are comparable."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def build_manifest(
    job: GenerationJob,
    *,
    runtime: dict,
    weights: dict,
    effective_config: dict,
    hardware: dict,
    artifacts: list[dict],
    warnings: list[str] | None = None,
) -> dict:
    """Assemble the manifest.

    ``requested`` keeps what the user asked for even when the effective values
    differ; nothing is normalised away silently. A difference between the two
    is surfaced in the UI rather than hidden.
    """
    requested = json.loads(job.config.model_dump_json())
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generation_id": job.id,
        "project_id": job.project_id,
        "created_at": utcnow().isoformat(),
        "requested_at": job.requested_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "title": job.title,
        "status": job.status.value,
        "runtime": runtime,
        "weights": weights,
        "request": requested,
        "effective_config": effective_config,
        "request_identity": job.request_identity,
        "hardware": {**hardware, "host": host_info()},
        "timing": json.loads(job.timing.model_dump_json()),
        "truncated": job.truncated,
        # Enough to explain, after the fact, why a run ended where it did.
        "token_budget": job.budget,
        "termination_reason": job.termination_reason,
        "effective_adjustments": job.effective_adjustments,
        "warnings": list(warnings or []) + list(job.warnings),
        "artifacts": artifacts,
    }
    manifest["manifest_identity"] = identity(
        {"request": requested, "effective_config": effective_config, "weights": weights}
    )
    return manifest


def hash_directory(directory: Path, *, skip: set[str] | None = None) -> dict[str, str]:
    """sha256 of every regular file under ``directory``, by relative path."""
    skip = skip or set()
    hashes: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = str(path.relative_to(directory))
        if relative in skip or relative.endswith(".tmp"):
            continue
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        hashes[relative] = digest.hexdigest()
    return hashes


def host_info() -> dict:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "hostname": platform.node(),
    }
