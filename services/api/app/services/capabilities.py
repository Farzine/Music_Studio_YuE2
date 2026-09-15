"""What this installation can actually do.

The static declarations in configs/yue2.capabilities.json are the starting
point; everything that can be checked on this machine is checked here. A
feature is advertised only when the thing it needs is present, so the UI never
offers a mode that would fail at generation time.
"""
from __future__ import annotations

import copy
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from yue2_studio_core.parameters import backend_capabilities, describe_registry
from yue2_studio_core.settings import Settings


def _ffmpeg_version() -> tuple[str | None, tuple[int, int] | None]:
    binary = shutil.which("ffmpeg")
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

    def local_models(self) -> list[dict[str, Any]]:
        """Model directories that are actually present, with their size."""
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        candidates = [
            ("model", self.settings.model_reference),
            ("vae", self.settings.vae_reference),
            ("vae", self.settings.vae_legacy_reference),
        ]
        for role, reference in candidates:
            path = Path(reference)
            present = path.is_dir()
            if reference in seen:
                continue
            seen.add(reference)
            weights = path / "model.safetensors"
            entries.append(
                {
                    "id": reference,
                    "role": role,
                    "label": path.name if present else reference,
                    "path": str(path) if present else None,
                    "present": present,
                    "is_local": present,
                    "bytes": weights.stat().st_size if weights.is_file() else None,
                }
            )
        return entries

    @lru_cache(maxsize=1)  # noqa: B019 - one process-lifetime probe is intended
    def runtime_probe(self) -> dict:
        ffmpeg_version, ffmpeg_parts = _ffmpeg_version()
        worker_venv = Path(self.settings._resolve(".venv-yue2"))
        compute = _compute_capability()
        return {
            "ffmpeg": {"version": ffmpeg_version, "parts": ffmpeg_parts, "present": ffmpeg_version is not None},
            "sheetsage2_present": self.settings.sheetsage2_path.is_dir(),
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
                f"SheetSage2 is not installed at {self.settings.sheetsage2_path}. See docs/cover-workflow.md.",
            )
        elif not ffmpeg_ok:
            set_state(
                "cover",
                False,
                f"SheetSage2 requires FFmpeg 6.1 or newer; this machine has {probe['ffmpeg']['version'] or 'none'}.",
            )
        else:
            set_state("cover", True)

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
        capabilities = self.capabilities(backend)
        options = [
            {"value": entry["id"], "label": entry["label"], "enabled": entry["present"], "role": entry["role"]}
            for entry in capabilities["models"]
            if entry["role"] == "model"
        ]
        options.insert(0, {"value": "", "label": "Default (from .env)", "enabled": True, "role": "model"})
        return describe_registry(copy.deepcopy(capabilities), {"models": options})
