"""What this installation can actually do.

The static declarations in configs/yue2.capabilities.json are the starting
point; everything that can be checked on this machine is checked here. A
feature is advertised only when the thing it needs is present, so the UI never
offers a mode that would fail at generation time.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from yue2_studio_core.delivery import format_catalogue
from yue2_studio_core.parameters import backend_capabilities, describe_registry
from yue2_studio_core.settings import Settings


def _ffmpeg_version(binary: str | None = None) -> tuple[str | None, tuple[int, int] | None]:
    binary = binary or shutil.which("ffmpeg")
    if not binary:
        return None, None
    try:
        output = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, timeout=10, check=False
        ).stdout.splitlines()
        first = output[0] if output else ""
        token = first.split("version", 1)[-1].strip().split(" ")[0]
        parts = token.lstrip("n").split(".")
        return token, (int(parts[0]), int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, None


def _venv_has_package(venv: Path, name: str) -> bool:
    for site in venv.glob("lib/python*/site-packages"):
        if (site / name).is_dir() or any(site.glob(f"{name}-*.dist-info")):
            return True
    return False


def _compute_capability() -> tuple[int, int] | None:
    try:
        import pynvml  # nvidia-ml-py

        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            major = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
            return (int(major[0]), int(major[1]))
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return None


class CapabilityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -- probes ----------------------------------------------------------- #

    @staticmethod
    def _describe_model(reference: str, role: str, *, is_default: bool = False) -> dict[str, Any]:
        path = Path(reference)
        present = path.is_dir()
        weights = path / "model.safetensors"
        config = path / "config.json"
        complete = present and weights.is_file() and config.is_file()
        problem = None
        if not present:
            problem = "The directory does not exist."
        elif not config.is_file():
            problem = "The directory has no config.json."
        elif not weights.is_file():
            problem = "The directory has no model.safetensors."
        return {
            "id": reference,
            "role": role,
            "label": path.name if present else reference,
            "path": str(path) if present else None,
            "present": complete,
            "is_local": present,
            "is_default": is_default,
            "bytes": weights.stat().st_size if weights.is_file() else None,
            "problem": problem,
        }

    def local_models(self) -> list[dict[str, Any]]:
        """Every model and decoder directory the studio knows about.

        Entries that are missing or incomplete are still listed, with the
        specific reason, so the selector can explain rather than simply omit.
        """
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        candidates = [
            ("model", self.settings.model_reference, True),
            ("vae", self.settings.vae_reference, True),
            ("vae", self.settings.vae_legacy_reference, False),
        ]
        for role, reference, is_default in candidates:
            if reference in seen:
                continue
            seen.add(reference)
            entries.append(self._describe_model(reference, role, is_default=is_default))

        # Any sibling directory that looks like a model is offered too, so a
        # second checkpoint can be dropped in without editing configuration.
        model_root = Path(self.settings.model_reference).parent
        if model_root.is_dir():
            for directory in sorted(model_root.iterdir()):
                reference = str(directory)
                if reference in seen or not directory.is_dir():
                    continue
                if not (directory / "config.json").is_file():
                    continue
                kind = None
                try:
                    kind = json.loads((directory / "config.json").read_text()).get("model_type")
                except (OSError, json.JSONDecodeError):
                    continue
                if kind not in {"yue2", "yue2_vae"}:
                    continue
                seen.add(reference)
                entries.append(self._describe_model(reference, "model" if kind == "yue2" else "vae"))
        return entries

    def resolve_model_choice(self, checkpoint: str) -> dict[str, Any] | None:
        """The inventory entry a configuration refers to, or None if unknown."""
        from yue2_studio_core.models import DEFAULT_MODEL

        if checkpoint == DEFAULT_MODEL:
            return self._describe_model(self.settings.model_reference, "model", is_default=True)
        for entry in self.local_models():
            if entry["id"] == checkpoint:
                return entry
        return None

    def runtime_probe(self) -> dict:
        """What is actually installed on this machine, checked each time.

        Not cached: the cover workflow can be installed while the API is
        running, and the System page should notice without a restart.
        """
        ffmpeg_binary = self.settings.ffmpeg_path
        ffmpeg_version, ffmpeg_parts = _ffmpeg_version(str(ffmpeg_binary) if ffmpeg_binary.is_file() else None)
        worker_venv = Path(self.settings._resolve(".venv-yue2"))
        sheetsage2_model = self.settings.sheetsage2_path
        compute = _compute_capability()
        return {
            "ffmpeg": {
                "version": ffmpeg_version,
                "parts": ffmpeg_parts,
                "present": ffmpeg_version is not None,
                "path": str(ffmpeg_binary) if ffmpeg_binary.is_file() else None,
            },
            #: Download formats this installation can actually produce, asked
            #: of the FFmpeg that is really here rather than assumed.
            "download_formats": format_catalogue(ffmpeg=ffmpeg_binary),
            "sheetsage2_present": (sheetsage2_model / "model.safetensors").is_file(),
            "sheetsage2_env": self.settings.sheetsage2_python.is_file(),
            "vae_legacy_present": Path(self.settings.vae_legacy_reference).is_dir(),
            "model_present": Path(self.settings.model_reference).is_dir(),
            "vae_present": Path(self.settings.vae_reference).is_dir(),
            "worker_venv": str(worker_venv) if worker_venv.is_dir() else None,
            "vllm_installed": worker_venv.is_dir() and _venv_has_package(worker_venv, "vllm"),
            "compute_capability": compute,
        }

    # -- capability assembly ---------------------------------------------- #

    def capabilities(self, backend: str | None = None) -> dict:
        backend = backend or self.settings.yue2_backend
        document = backend_capabilities(backend)
        probe = self.runtime_probe()
        entries = document["capabilities"]

        def set_state(name: str, supported: bool, reason: str | None = None, note: str | None = None) -> None:
            entry = entries.setdefault(name, {})
            entry["supported"] = supported
            if supported:
                entry.pop("reason", None)
            elif reason:
                entry["reason"] = reason
            if note:
                entry["note"] = note

        # Cover needs the transcription model and a modern FFmpeg, per the
        # SheetSage2 setup documented upstream.
        ffmpeg_parts = probe["ffmpeg"]["parts"]
        ffmpeg_ok = bool(ffmpeg_parts and ffmpeg_parts >= (6, 1))
        if backend == "mock":
            set_state("cover", False, "The mock backend does not transcribe audio.")
        elif not probe["sheetsage2_present"]:
            set_state(
                "cover",
                False,
                f"SheetSage2 weights are not installed at {self.settings.sheetsage2_path}. "
                "Run scripts/setup_cover.sh.",
            )
        elif not probe["sheetsage2_env"]:
            set_state(
                "cover",
                False,
                f"The SheetSage2 environment is missing at {self.settings.sheetsage2_python.parent.parent}. "
                "Run scripts/setup_cover.sh.",
            )
        elif not ffmpeg_ok:
            set_state(
                "cover",
                False,
                f"SheetSage2 needs FFmpeg 6.1 or newer; the one found is {probe['ffmpeg']['version'] or 'missing'}. "
                "Run scripts/setup_cover.sh to install a private build.",
            )
        else:
            set_state(
                "cover",
                True,
                note="Transcription is an estimate of the recording, not an exact copy of it.",
            )

        set_state(
            "output_mp3",
            probe["ffmpeg"]["present"],
            "FFmpeg was not found on PATH, so MP3 conversion is unavailable.",
        )
        set_state(
            "vae_legacy",
            probe["vae_legacy_present"],
            f"m-a-p/YuE2-Vae-legacy is not present at {self.settings.vae_legacy_reference}.",
        )
        if backend == "native":
            set_state(
                "backend_vllm",
                probe["vllm_installed"],
                "vLLM is not installed in the worker environment. Install the optional 'fast' extras.",
            )
            compute = probe["compute_capability"]
            fp8_ok = bool(compute and compute >= (8, 9))
            set_state(
                "quantization_fp8",
                fp8_ok,
                (
                    f"The GPU reports compute capability {compute[0]}.{compute[1]}; FP8 needs 8.9 or newer."
                    if compute
                    else "No CUDA device was detected, so FP8 support cannot be confirmed."
                ),
            )

        # A mode is only offered when every capability it depends on is present.
        modes = [mode for mode in document["modes"]]
        if entries.get("cover", {}).get("supported"):
            if "cover" not in modes:
                modes.append("cover")
        else:
            modes = [mode for mode in modes if mode != "cover"]
        document["modes"] = modes
        document["backend"] = backend
        document["probe"] = probe
        document["models"] = self.local_models()
        return document

    def schema(self, backend: str | None = None) -> dict:
        from yue2_studio_core.models import DEFAULT_MODEL

        capabilities = self.capabilities(backend)
        default = self._describe_model(self.settings.model_reference, "model", is_default=True)
        options = [
            {
                "value": DEFAULT_MODEL,
                "label": f"Default — {default['label']}",
                "enabled": default["present"],
                "disabled_reason": default["problem"],
                "role": "model",
                "bytes": default["bytes"],
                "path": default["path"],
                "is_default": True,
                "help": "Uses the model configured in .env.",
            }
        ]
        for entry in capabilities["models"]:
            if entry["role"] != "model" or entry["is_default"]:
                continue
            options.append(
                {
                    "value": entry["id"],
                    "label": entry["label"],
                    "enabled": entry["present"],
                    "disabled_reason": entry["problem"],
                    "role": "model",
                    "bytes": entry["bytes"],
                    "path": entry["path"],
                    "is_default": False,
                }
            )
        return describe_registry(copy.deepcopy(capabilities), {"models": options})
