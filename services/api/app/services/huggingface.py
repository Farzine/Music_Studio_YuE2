"""Repository inspection and download planning; no tensors, transfers or registry writes."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath

from huggingface_hub import HfApi, hf_hub_url
from huggingface_hub.utils import (
    EntryNotFoundError, GatedRepoError, HFValidationError, HfHubHTTPError,
    RepositoryNotFoundError, RevisionNotFoundError, build_hf_headers,
    get_session, hf_raise_for_status, validate_repo_id,
)
from requests.exceptions import RequestException

from yue2_studio_core.errors import NotFoundError, ValidationError
from yue2_studio_core.model_metadata import (
    GGUF_COMPANIONS, NATIVE_COMPANIONS, ModelMetadata, model_config_compatibility,
    model_required_files, unique_json_object,
)
from yue2_studio_core.settings import Settings

METADATA_LIMIT = 1024**2


def validate_source(repo_id: str, filename: str | None = None, revision: str | None = None) -> None:
    try:
        validate_repo_id(repo_id)
    except HFValidationError as exc:
        raise ValidationError("Enter a valid Hugging Face model ID, such as owner/repository.") from exc
    if filename is not None:
        path = PurePosixPath(filename)
        if (not filename or path.is_absolute() or "\\" in filename or ":" in filename
                or any(ord(c) < 32 for c in filename)
                or any(part in {"", ".", ".."} for part in filename.split("/"))):
            raise ValidationError("Choose a relative file path inside the model repository.")
    if revision and (not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", revision) or ".." in revision):
        raise ValidationError("Enter a valid branch, tag or commit revision.")


def hub_error(exc: Exception, repo_id: str, revision: str | None = None):
    """Safe messages: upstream exceptions can contain request URLs or credentials."""
    if isinstance(exc, RevisionNotFoundError):
        return NotFoundError(f"Revision {revision or 'main'} was not found in {repo_id}; choose an available branch, tag or commit.")
    if isinstance(exc, EntryNotFoundError):
        return NotFoundError(f"The requested file was not found in {repo_id}; inspect the selected revision again.")
    if isinstance(exc, GatedRepoError):
        return ValidationError(f"Access to {repo_id} requires authorization; accept the repository terms and configure HF_TOKEN on the API host.")
    if isinstance(exc, RepositoryNotFoundError):
        return NotFoundError(f"Repository {repo_id} was not found or is private; check the ID and the API host's HF_TOKEN.")
    if isinstance(exc, HfHubHTTPError) and getattr(exc.response, "status_code", None) in {401, 403}:
        return ValidationError(f"Access to {repo_id} was denied; check the API host's HF_TOKEN and repository permissions.")
    return ValidationError(f"Could not contact Hugging Face for {repo_id}; check the network connection and retry.",
                           details={"reason": "huggingface_unavailable", "retryable": True})


def installation_path(settings: Settings, repo_id: str, commit: str, filename: str) -> Path:
    digest = hashlib.sha256(f"{repo_id}@{commit}/{filename}".encode()).hexdigest()[:12]
    return settings.models_path / "hub" / f"{repo_id.replace('/', '--')}--{digest}"


def default_download_files(filename: str, names: set[str]) -> list[str]:
    companions = GGUF_COMPANIONS if filename.lower().endswith(".gguf") else NATIVE_COMPANIONS
    if filename.lower().endswith(".gguf") and not all(name in names for name in companions):
        return [filename]
    return [filename, *(name for name in companions if name in names and name != filename)]


def _size(value) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


class HuggingFaceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _json(self, repo_id: str, commit: str, filename: str, files: dict) -> dict:
        if filename not in files:
            return {}
        if (files[filename]["bytes"] or 0) > METADATA_LIMIT:
            raise ValueError(f"{filename} exceeds the 1 MiB inspection limit.")
        # Stream only bounded JSON, never model weights or executable remote code.
        with get_session().get(hf_hub_url(repo_id, filename, revision=commit),
                               headers=build_hf_headers(), timeout=20, stream=True) as response:
            hf_raise_for_status(response)
            payload = bytearray()
            for chunk in response.iter_content(64 * 1024):
                payload.extend(chunk)
                if len(payload) > METADATA_LIMIT:
                    raise ValueError(f"{filename} exceeds the 1 MiB inspection limit.")
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_json_object)
        if not isinstance(value, dict):
            raise ValueError(f"{filename} must contain a JSON object.")
        return value

    def inspect(self, repo_id: str, revision: str | None = None) -> dict:
        validate_source(repo_id, revision=revision)
        api = HfApi()
        try:
            info = api.model_info(repo_id, revision=revision or "main", files_metadata=True, timeout=20)
        except (HfHubHTTPError, RequestException) as exc:
            raise hub_error(exc, repo_id, revision) from exc
        commit = info.sha
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
            raise ValidationError("Hugging Face did not return an immutable commit; inspect the repository again.")
        files = {}
        for item in info.siblings or []:
            validate_source(repo_id, item.rfilename)
            lfs = getattr(item, "lfs", None)
            size = _size(getattr(item, "size", None))
            files[item.rfilename] = {
                "name": item.rfilename, "bytes": size if size is not None else _size(getattr(lfs, "size", None)),
                "extension": PurePosixPath(item.rfilename).suffix.lower(),
                "checksum_sha256": getattr(lfs, "sha256", None),
            }
        warnings, refs = [], []
        try:
            available = api.list_repo_refs(repo_id)
            refs = [dict(name=ref.name, kind=kind, commit_hash=ref.target_commit)
                    for kind, values in (("branch", available.branches), ("tag", available.tags)) for ref in values]
        except (HfHubHTTPError, RequestException) as exc:
            warnings.append(hub_error(exc, repo_id).message + " Branches/tags could not be listed; an explicit revision still works.")
        configs = {}
        for name in ("config.json", "sidecars/yue2-model-config.json", "sidecars/yue2-vae-config.json"):
            try:
                configs[name] = self._json(repo_id, commit, name, files)
            except (HfHubHTTPError, RequestException) as exc:
                warnings.append(hub_error(exc, repo_id, commit).message + f" Metadata {name} is unavailable.")
                configs[name] = {}
            except (ValueError, RecursionError) as exc:
                warnings.append(f"Could not inspect {name}: {exc}")
                configs[name] = {}
        candidates, contexts = [], {}
        for file in sorted(files.values(), key=lambda f: f["name"]):
            if file["extension"] not in {".gguf", ".safetensors"}:
                continue
            filename = file["name"]
            gguf = file["extension"] == ".gguf"
            config = configs["sidecars/yue2-model-config.json" if gguf else "config.json"]
            # These are decoder artifacts for the existing audio.cpp package.
            role = "vae" if (gguf and filename.startswith("yue2-vae-")) or config.get("model_type") == "yue2_vae" else "model"
            if role == "vae" and gguf:
                config = configs["sidecars/yue2-vae-config.json"]
            compatibility, problem = model_config_compatibility(filename, role, config, configs["sidecars/yue2-vae-config.json"])
            missing = [name for name in model_required_files(filename) if name not in files] if role == "model" else []
            if missing:
                compatibility, problem = "incompatible", "Repository lacks required adapter files: " + ", ".join(missing)
            parameters = config.get("parameter_count", config.get("num_parameters"))
            parameters = _size(parameters) or None
            model_id = f"hf:{repo_id}@{commit}/{filename}"
            descriptor = ModelMetadata(
                id=model_id, role=role, label=f"{repo_id} · {filename}", path=None, is_local=False,
                bytes=file["bytes"], filename=filename, format="gguf" if gguf else "safetensors",
                source="huggingface", huggingface_repo=repo_id, revision=revision or "main", commit_hash=commit,
                architecture=config.get("model_type") if isinstance(config.get("model_type"), str) else None,
                parameter_count=parameters, checksum_sha256=file["checksum_sha256"],
                backend="audiocpp" if gguf else "native", download_status="missing", files_complete=False,
                compatibility_status=compatibility, inference_status="incompatible" if compatibility == "incompatible" else "files_missing",
                problem=problem,
            ).model_dump(mode="json")
            hint = re.search(r"(?:^|[-_.])(Q\d+(?:_[A-Z0-9]+)*|BF16|F16|F32)(?=[-_.]|$)", filename.upper())
            candidates.append({"model": descriptor, "required_files": list(model_required_files(filename)) if role == "model" else [filename],
                               "missing_files": missing, "quantization_hint": hint.group(1) if hint else None,
                               "metadata_basis": "repository_configuration; weight headers not validated"})
            contexts[model_id] = {"model_config": config, "bundled_vae_bytes": files.get(GGUF_COMPANIONS[0], {}).get("bytes") if gguf else None}
        card = getattr(info, "card_data", None)
        card = card.to_dict() if hasattr(card, "to_dict") else card if isinstance(card, dict) else {}
        return {"repo_id": repo_id, "requested_revision": revision or "main", "revision": commit,
                "description": card.get("description") if isinstance(card.get("description"), str) else None,
                "license": card.get("license") if isinstance(card.get("license"), str) else None,
                "gated": getattr(info, "gated", None), "private": getattr(info, "private", None),
                "revisions": sorted(refs, key=lambda r: (r["kind"], r["name"])),
                "files": sorted(files.values(), key=lambda f: f["name"]), "candidates": candidates,
                "warnings": warnings, "candidate_contexts": contexts}

    def preview(self, inspection: dict, filename: str, *, mode: str = "single", selected_files: list[str] | None = None) -> dict:
        repo_id, commit = inspection["repo_id"], inspection["revision"]
        validate_source(repo_id, filename, commit)
        files = {f["name"]: f for f in inspection["files"]}
        if filename not in files:
            raise NotFoundError(f"File {filename} does not exist in {repo_id}@{commit}.")
        if not filename.lower().endswith((".gguf", ".safetensors")):
            raise ValidationError("Choose a GGUF or safetensors primary model file.")
        if mode == "single":
            names = default_download_files(filename, set(files))
        elif mode == "repository":
            names = sorted(files)
        elif mode == "selected":
            names = list(dict.fromkeys([filename, *(selected_files or [])]))
        else:
            raise ValidationError("Choose single, selected or repository download mode.")
        for name in names:
            validate_source(repo_id, name)
            if name not in files:
                raise NotFoundError(f"File {name} does not exist in {repo_id}@{commit}.")
        known = sum(files[name]["bytes"] or 0 for name in names)
        unknown = [name for name in names if files[name]["bytes"] is None]
        destination = installation_path(self.settings, repo_id, commit, filename)
        existing = self.settings.models_path.resolve()
        while not existing.exists():
            existing = existing.parent
        if not existing.is_dir():
            raise ValidationError(f"Model storage path {existing} is a file; configure a directory before downloading.")
        free = shutil.disk_usage(existing).free
        insufficient = known + 2**30 > free
        required = model_required_files(filename)
        missing = [name for name in required if name not in names]
        return {"repo_id": repo_id, "revision": commit, "requested_revision": inspection["requested_revision"],
                "filename": filename, "mode": mode, "files": [files[name] for name in names],
                "total_bytes": None if unknown else known, "known_bytes": known, "unknown_size_files": unknown,
                "destination": str(destination), "storage_path": str(existing), "free_bytes": free,
                "safety_margin_bytes": 2**30, "disk_status": "insufficient" if insufficient else "unknown" if unknown else "sufficient",
                "can_download": not insufficient, "missing_required_files": missing,
                "candidate": next(c for c in inspection["candidates"] if c["model"]["filename"] == filename),
                "warnings": [*inspection["warnings"],
                             *(["Insufficient disk space for the known content plus 1 GiB of headroom."] if insufficient else []),
                             *(["Some file sizes are unknown; available storage cannot be guaranteed."] if unknown else []),
                             *(["Selection omits required adapter files; it will not be inference ready."] if missing else [])]}

    def discover(self, base_model: str, limit: int = 10) -> dict:
        validate_source(base_model)
        if not 1 <= limit <= 20:
            raise ValidationError("Choose a discovery limit between 1 and 20 repositories.")
        try:
            results = list(HfApi().list_models(filter=f"base_model:quantized:{base_model}", limit=limit))
        except (HfHubHTTPError, RequestException) as exc:
            raise hub_error(exc, base_model) from exc
        # ponytail: inspect at most 20 repositories sequentially; add bounded
        # concurrency if measured discovery latency requires it.
        items = []
        for result in sorted(results, key=lambda r: r.id):
            try:
                items.append(self.inspect(result.id))
            except (ValidationError, NotFoundError) as exc:
                items.append({"repo_id": result.id, "error": exc.to_dict(), "candidates": [], "candidate_contexts": {}})
        return {"base_model": base_model, "filter": f"base_model:quantized:{base_model}", "items": items,
                "limit": limit, "note": "Hub lineage tags identify candidates, not verified compatibility. No weights downloaded."}
