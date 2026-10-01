"""Bounded host path selection. Lists metadata only, never arbitrary file contents."""
from pathlib import Path

from yue2_studio_core.errors import NotFoundError, ValidationError
from yue2_studio_core.model_metadata import read_json_object, read_model_metadata


class LocalPaths:
    def __init__(self, settings, registry):
        self.settings, self.registry = settings, registry

    def roots(self) -> list[str]:
        references = [*self.settings.model_browser_roots, self.settings.yue2_model_path,
                      self.settings.yue2_vae_path, self.settings.yue2_vae_legacy_path]
        candidates = [self.settings.models_path, *(self.settings._resolve(p) for p in references if p.strip())]
        return sorted({str(p.resolve()) for p in candidates if p.is_dir()})

    def resolve(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            raise ValidationError("Choose an absolute path from the model browser.")
        try:
            path = path.resolve(strict=True)
            roots = [Path(root) for root in self.roots()]
            root = next((root for root in roots if path.is_relative_to(root)), None)
            if root is None or any(part.startswith(".") for part in path.relative_to(root).parts):
                raise ValidationError("Path is outside the configured model browser roots or is private staging. Add a trusted MODEL_BROWSER_ROOTS directory in .env if needed.")
            return path
        except (OSError, RuntimeError) as exc:
            raise NotFoundError(f"The selected path does not exist or cannot be read: {exc}") from exc

    def browse(self, value: str | None = None) -> dict:
        roots = self.roots()
        if value is None:
            return {"roots": roots, "path": None, "parent": None, "items": [], "truncated": False}
        path = self.resolve(value)
        if not path.is_dir():
            raise ValidationError("Choose a directory to browse.")
        items = []
        try:
            # ponytail: bounded directory listing; paginate if model folders exceed 1000 entries.
            truncated = False
            for child in path.iterdir():
                if child.name.startswith(".") or child.is_symlink():
                    continue
                if len(items) >= 1000:
                    truncated = True
                    break
                if child.is_dir() or child.is_file():
                    items.append({"name": child.name, "path": str(child), "kind": "directory" if child.is_dir() else "file",
                                  "bytes": child.stat().st_size if child.is_file() else None})
            parent = str(path.parent) if any(path.parent.is_relative_to(Path(root)) for root in roots) else None
            return {"roots": roots, "path": str(path), "parent": parent,
                    "items": sorted(items, key=lambda i: (i["kind"] != "directory", i["name"])), "truncated": truncated}
        except OSError as exc:
            raise ValidationError(f"Cannot list this model directory: {exc}. Check its permissions.") from exc

    def validate(self, value: str, kind: str) -> dict:
        path = self.resolve(value)
        if kind == "file" and not path.is_file() or kind == "directory" and not path.is_dir():
            raise ValidationError(f"Choose an existing {kind}.")
        if kind == "file" and path.suffix.lower() not in {".safetensors", ".gguf"}:
            raise ValidationError("Choose a safetensors or GGUF model file.")
        return {"path": str(path), "kind": kind, "exists": True}

    def register(self, value: str, kind: str) -> dict:
        chosen = self.validate(value, kind)
        path = Path(chosen["path"])
        directory = path.parent if kind == "file" else path
        try:
            metadata = read_model_metadata(str(directory))
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Installation metadata cannot be read: {exc}. Repair studio-model.json before registering.") from exc
        if kind == "file" and path.name != metadata.get("filename", "model.safetensors"):
            raise ValidationError("This file is not the primary weight file in its installation metadata. GGUF packages require studio-model.json and their sidecars; inspect the installation directory or use Download Model.")
        try:
            config = read_json_object(directory / ("sidecars/yue2-model-config.json" if metadata.get("filename", "").endswith(".gguf") else "config.json"))
            role = "vae" if config.get("model_type") == "yue2_vae" else "model"
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Select a model installation with readable configuration: {exc}") from exc
        entry = self.registry.register(str(directory), role)
        return {"model": entry.model_dump(mode="json"), "selection": chosen}
