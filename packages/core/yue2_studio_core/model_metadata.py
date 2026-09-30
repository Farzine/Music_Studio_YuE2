"""Shared installation facts and preflight readiness; no inference imports.

File presence is not content validation. Readiness means the existing adapter's
file/runtime prerequisites are met, not that a load or GPU memory test passed.
"""
from __future__ import annotations

import json
import os
import shutil
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, computed_field

from .models import DEFAULT_MODEL
from .settings import Settings


GGUF_COMPANIONS = (
    "yue2-vae-f16.gguf", "sidecars/yue2-model-config.json",
    "sidecars/yue2-generation-config.json", "sidecars/yue2-qwen.tiktoken",
    "sidecars/yue2-vae-config.json",
)

MAX_METADATA_BYTES = 100_000_000


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate metadata key: {key}")
        result[key] = value
    return result


def read_json_object(path: Path) -> dict:
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError(f"{path.name} exceeds the metadata size limit.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_json_object)
    except RecursionError as exc:
        raise ValueError(f"{path.name} contains overly nested metadata.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return value


class ModelFacts(BaseModel):
    """Installation metadata shared by durable records and live descriptors."""

    bytes: int | None = None
    format: Literal["safetensors", "gguf", "unknown"]
    filename: str | None = None
    source: Literal["local", "huggingface"] = "local"
    huggingface_repo: str | None = None
    revision: str | None = None
    commit_hash: str | None = None
    architecture: str | None = None
    parameter_count: int | None = None
    quantization: str | None = None
    precision: str | None = None
    backend: str | None = None
    tensor_element_count: int | None = None
    checksum_sha256: str | None = None


class ModelMetadata(ModelFacts):
    """Inventory descriptor, retaining legacy names for existing consumers."""

    id: str
    role: Literal["model", "vae"]
    label: str
    path: str | None
    is_local: bool
    is_default: bool = False
    registry_id: str | None = None
    aliases: list[str] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None
    download_status: Literal["missing", "downloaded", "unknown"]
    files_complete: bool
    validation_status: Literal["not_validated", "validated", "failed"] = "not_validated"
    deletion_status: Literal["active", "deleting"] = "active"
    registration_status: Literal["discovered", "registered"] = "discovered"
    compatibility_status: Literal["supported", "incompatible", "unknown"]
    inference_status: Literal[
        "ready", "files_missing", "runtime_unavailable", "incompatible", "validation_failed", "unknown",
    ]
    problem: str | None = None
    # Only the worker can establish residency; inventory discovery cannot.
    currently_loaded: bool | None = None

    @computed_field
    @property
    def inference_ready(self) -> bool:
        return self.inference_status == "ready"

    @computed_field
    @property
    def present(self) -> bool:
        """Legacy readiness projection, never used to describe file presence."""
        return self.inference_ready


def resolve_model_reference(choice: str, settings: Settings) -> str:
    choice = (choice or "").strip()
    return settings.model_reference if choice in {"", DEFAULT_MODEL} else choice


def resolve_vae_reference(choice: str, settings: Settings) -> str:
    choice = (choice or "").strip()
    if choice in {"", "standard", DEFAULT_MODEL}:
        return settings.vae_reference
    return settings.vae_legacy_reference if choice == "legacy" else choice


def vae_compatibility_error(model_reference: str, vae_reference: str) -> str | None:
    """Compare declared native latent widths; unknown widths are not invented."""
    model = read_json_object(Path(model_reference) / "config.json")
    vae = read_json_object(Path(vae_reference) / "config.json")
    model_dim = model.get("latent_dim")
    decoder = vae.get("decoder_config")
    vae_dim = decoder.get("latent_dim") if isinstance(decoder, dict) else vae.get("latent_dim")
    if type(model_dim) is int and type(vae_dim) is int and model_dim != vae_dim:
        return f"VAE latent width {vae_dim} does not match the model latent width {model_dim}; select a compatible VAE."
    return None


def audiocpp_available(settings: Settings) -> bool:
    executable = settings.audiocpp_executable
    return bool(shutil.which(executable) or (Path(executable).is_file() and os.access(executable, os.X_OK)))


def read_model_metadata(reference: str) -> dict:
    path = Path(reference)
    metadata = path / "studio-model.json"
    if not metadata.is_file():
        return {}
    value = read_json_object(metadata)
    for key in ("repo_id", "revision"):
        if value.get(key) is not None and not isinstance(value[key], str):
            raise ValueError(f"studio-model.json {key} must be a string.")
    filename = value.get("filename")
    if not isinstance(filename, str) or not filename or Path(filename).is_absolute():
        raise ValueError("studio-model.json must name a relative model file.")
    if ".." in Path(filename).parts or not (path / filename).resolve().is_relative_to(path.resolve()):
        raise ValueError("The model file must be inside its installation directory.")
    return value


def is_gguf_model(reference: str) -> bool:
    try:
        return str(read_model_metadata(reference).get("filename", "")).lower().endswith(".gguf")
    except (OSError, ValueError):
        return False


def describe_model_files(reference: str, role: Literal["model", "vae"], *, is_default: bool = False) -> ModelMetadata:
    """Apply the existing YuE2 adapter's file requirements in one shared place."""
    path = Path(reference)
    local = path.is_dir()
    base = dict(id=reference, role=role, label=path.name if local else reference,
                path=reference if local else None, is_local=local, is_default=is_default)
    try:
        metadata = read_model_metadata(reference)
    except (OSError, ValueError) as exc:
        return ModelMetadata(**base, format="unknown", files_complete=False,
                             download_status="unknown", validation_status="failed",
                             compatibility_status="unknown", inference_status="validation_failed",
                             problem=f"Cannot read model installation metadata: {exc}")

    filename = metadata.get("filename") or "model.safetensors"
    suffix = Path(filename).suffix.lower()
    gguf = suffix == ".gguf"
    weights = path / filename
    downloaded = weights.is_file()
    problem = None
    compatibility = "supported"
    if gguf:
        missing = [name for name in GGUF_COMPANIONS if not (path / name).is_file()]
        complete = downloaded and not missing
        if not downloaded:
            problem = f"The selected file {filename} is missing."
        elif missing:
            problem = "Missing YuE2 GGUF companion files: " + ", ".join(missing)
    else:
        complete = local and downloaded and (path / "config.json").is_file()
        if not local:
            problem = "The directory does not exist."
        elif not (path / "config.json").is_file():
            problem = "The directory has no config.json."
        elif not downloaded:
            problem = f"The directory has no {filename}."

    status = "ready" if complete else "files_missing"
    if suffix not in {".gguf", ".safetensors"} or (not gguf and filename != "model.safetensors"):
        compatibility = "incompatible"
        problem = "The current native adapter requires model.safetensors in the installation root; this file/layout is not supported."
    architecture, precision = None, None
    config_path = path / ("sidecars/yue2-model-config.json" if gguf else "config.json")
    if config_path.is_file():
        try:
            config = read_json_object(config_path)
            architecture = config.get("model_type") if isinstance(config.get("model_type"), str) else None
            expected = "yue2" if role == "model" else "yue2_vae"
            if architecture != expected:
                compatibility = "incompatible" if architecture else "unknown"
                problem = f"Expected {expected} architecture; config.json declares {architecture or 'Unknown'}."
            if gguf and (path / "sidecars/yue2-vae-config.json").is_file():
                vae_config = read_json_object(path / "sidecars/yue2-vae-config.json")
                if vae_config.get("model_type") != "yue2_vae":
                    compatibility = "incompatible"
                    problem = "The bundled VAE configuration does not declare yue2_vae architecture."
        except (OSError, ValueError, RecursionError) as exc:
            return ModelMetadata(**base, format="gguf" if gguf else "safetensors", filename=filename, files_complete=complete,
                                 download_status="downloaded" if downloaded else "missing", validation_status="failed",
                                 compatibility_status="unknown", inference_status="validation_failed", problem=str(exc))
    if complete and compatibility == "incompatible":
        status = "incompatible"
        problem = problem or "This GGUF file is not a supported YuE2 main model."
    elif complete and compatibility == "unknown":
        status = "unknown"
    return ModelMetadata(
        **{**base, "label": f"{metadata.get('repo_id') or path.name} · {filename}" if gguf else base["label"]},
        bytes=weights.stat().st_size if downloaded else None,
        filename=filename, format="gguf" if gguf else "safetensors" if suffix == ".safetensors" else "unknown",
        architecture=architecture, precision=precision,
        source="huggingface" if metadata.get("repo_id") else "local",
        huggingface_repo=metadata.get("repo_id"), revision=metadata.get("revision"),
        commit_hash=(metadata.get("revision") if re.fullmatch(r"[0-9a-fA-F]{40}", metadata.get("revision") or "") else None),
        backend="audiocpp" if gguf else "native",
        download_status="downloaded" if downloaded else "missing",
        files_complete=complete, compatibility_status=compatibility,
        inference_status=status, problem=problem,
    )
