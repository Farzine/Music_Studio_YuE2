"""Environment-backed settings shared by the API process and the GPU worker.

Nothing in the application hard-codes a model path, a data directory or a
concurrency limit; every such value is read here.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    """Repository root: three levels above this file (packages/core/<pkg>)."""
    return Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(repo_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    app_env: str = "development"

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_url: str = "http://127.0.0.1:3000"

    yue2_model_path: str = "./models/YuE2-3B"
    yue2_vae_path: str = "./models/YuE2-Vae"
    yue2_vae_legacy_path: str = "./models/YuE2-Vae-legacy"
    sheetsage2_model_path: str = "./models/SheetSage2"
    sheetsage2_venv: str = "./.venv-sheetsage2"
    sheetsage2_timeout_seconds: int = 1800
    #: A private FFmpeg, so the cover workflow does not depend on the system one
    #: being new enough (SheetSage2 needs 6.1+; Ubuntu 22.04 ships 4.4.2).
    ffmpeg_dir: str = "./tools/ffmpeg"
    yue2_model_revision: str | None = None
    yue2_vae_revision: str | None = None

    data_dir: str = "./data"
    configs_dir: str = "./configs"

    max_concurrent_gpu_jobs: int = 1
    worker_id: str = "local-gpu-0"
    worker_poll_interval_seconds: float = 0.5
    #: How often a running job re-reads its own record to notice a cancellation.
    cancel_poll_interval_seconds: float = 0.25
    yue2_backend: str = Field(default="native", description="native | mock | comfy")

    model_idle_unload_seconds: int = 0
    yue2_memory_budget_gib: float = 40.0
    yue2_compute_backend: str = "torch"
    yue2_quantization: str = "none"
    yue2_offload_ar: bool = False
    yue2_local_files_only: bool = True

    comfy_api_url: str | None = None
    comfy_workflow_path: str = "./yue2_full.json"

    max_upload_bytes: int = 100 * 1024 * 1024

    @field_validator("yue2_backend")
    @classmethod
    def _check_backend(cls, value: str) -> str:
        allowed = {"native", "mock", "comfy"}
        if value not in allowed:
            raise ValueError(f"YUE2_BACKEND must be one of {sorted(allowed)}")
        return value

    @field_validator("max_concurrent_gpu_jobs")
    @classmethod
    def _check_concurrency(cls, value: int) -> int:
        if value < 1:
            raise ValueError("MAX_CONCURRENT_GPU_JOBS must be at least 1")
        return value

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (repo_root() / path).resolve()

    @property
    def data_path(self) -> Path:
        return self._resolve(self.data_dir)

    @property
    def configs_path(self) -> Path:
        return self._resolve(self.configs_dir)

    @property
    def model_reference(self) -> str:
        """Local directory when it exists, otherwise the Hugging Face repo id.

        Returning the repo id keeps a fresh checkout usable; the worker still
        records the resolved directory and file hashes in every manifest.
        """
        path = self._resolve(self.yue2_model_path)
        return str(path) if path.is_dir() else "m-a-p/YuE2-3B"

    @property
    def vae_reference(self) -> str:
        path = self._resolve(self.yue2_vae_path)
        return str(path) if path.is_dir() else "m-a-p/YuE2-Vae"

    @property
    def vae_legacy_reference(self) -> str:
        path = self._resolve(self.yue2_vae_legacy_path)
        return str(path) if path.is_dir() else "m-a-p/YuE2-Vae-legacy"

    @property
    def sheetsage2_path(self) -> Path:
        return self._resolve(self.sheetsage2_model_path)

    @property
    def sheetsage2_python(self) -> Path:
        return self._resolve(self.sheetsage2_venv) / "bin" / "python"

    @property
    def ffmpeg_path(self) -> Path:
        """The bundled FFmpeg if present, otherwise whatever is on PATH."""
        bundled = self._resolve(self.ffmpeg_dir) / "ffmpeg"
        if bundled.is_file():
            return bundled
        import shutil

        found = shutil.which("ffmpeg")
        return Path(found) if found else bundled

    @property
    def cuda_visible_devices(self) -> str | None:
        return os.environ.get("CUDA_VISIBLE_DEVICES")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
