"""GPU, disk, worker and queue state for the System page.

GPU numbers come from NVML. Runtime versions and model residency come from the
worker's heartbeat file, because the API process deliberately does not import
torch or the YuE2 runtime.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yue2_studio_core.models import JobStatus
from yue2_studio_core.queue import FilesystemJobQueue
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store

HEARTBEAT_STALE_AFTER = timedelta(seconds=30)


def _gpus() -> tuple[list[dict], str | None, str | None]:
    try:
        import pynvml
    except ImportError:
        return [], None, "nvidia-ml-py is not installed in the API environment."
    try:
        pynvml.nvmlInit()
    except Exception as exc:  # NVML absent or no driver
        return [], None, f"NVML unavailable: {exc}"
    try:
        driver = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver, bytes):
            driver = driver.decode()
        devices = []
        for index in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            name = pynvml.nvmlDeviceGetName(handle)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            capability = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
            try:
                utilisation = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            except Exception:
                utilisation = None
            try:
                temperature = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                temperature = None
            devices.append(
                {
                    "index": index,
                    "name": name.decode() if isinstance(name, bytes) else name,
                    "memory_total_bytes": int(memory.total),
                    "memory_used_bytes": int(memory.used),
                    "memory_free_bytes": int(memory.free),
                    "compute_capability": f"{capability[0]}.{capability[1]}",
                    "utilisation_percent": utilisation,
                    "temperature_c": temperature,
                }
            )
        return devices, driver, None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


class SystemInfoService:
    def __init__(self, settings: Settings, store: Store, queue: FilesystemJobQueue) -> None:
        self.settings = settings
        self.store = store
        self.queue = queue

    @property
    def worker_dir(self) -> Path:
        return self.store.root / "worker"

    def worker_state(self) -> dict:
        directory = self.worker_dir
        workers = []
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                seen = payload.get("updated_at")
                stale = True
                if seen:
                    try:
                        stale = datetime.now(timezone.utc) - datetime.fromisoformat(seen) > HEARTBEAT_STALE_AFTER
                    except ValueError:
                        stale = True
                payload["stale"] = stale
                payload["online"] = not stale
                workers.append(payload)
        return {"workers": workers, "online": any(worker["online"] for worker in workers)}

    def info(self) -> dict:
        devices, driver, gpu_error = _gpus()
        usage = shutil.disk_usage(self.store.root)
        jobs = self.store.list_jobs()
        by_status: dict[str, int] = {}
        for job in jobs:
            by_status[job.status.value] = by_status.get(job.status.value, 0) + 1
        active = [job for job in jobs if job.status.is_active]
        return {
            "app": {
                "env": self.settings.app_env,
                "backend": self.settings.yue2_backend,
                "data_dir": str(self.store.root),
                "max_concurrent_gpu_jobs": self.settings.max_concurrent_gpu_jobs,
                "cuda_visible_devices": self.settings.cuda_visible_devices,
            },
            "gpus": devices,
            "driver_version": driver,
            "gpu_error": gpu_error,
            "disk": {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "path": str(self.store.root),
            },
            "queue": {
                "depth": self.queue.depth(),
                "active": [
                    {"id": job.id, "title": job.title, "status": job.status.value, "stage": job.progress.stage}
                    for job in active
                ],
                "by_status": by_status,
                "total_generations": len(jobs),
            },
            "worker": self.worker_state(),
            "models": {
                "model": self.settings.model_reference,
                "vae": self.settings.vae_reference,
                "model_present": Path(self.settings.model_reference).is_dir(),
                "vae_present": Path(self.settings.vae_reference).is_dir(),
            },
        }

    def vram_risk(self, requested_seconds: float, decoder_mode: str, budget_gib: float) -> dict | None:
        """Warn before starting when the request looks too large for the GPU.

        This never changes the request. It reports an estimate based on the
        free memory NVML reports and the decoder mode, and says so.
        """
        devices, _, _ = _gpus()
        if not devices:
            return None
        device = devices[0]
        free_gib = device["memory_free_bytes"] / 2**30
        # A whole-song decode holds the full waveform and its activations; the
        # tiled path is bounded by the tile. These coefficients are rough and
        # are presented to the user as an estimate, not a guarantee.
        estimate_gib = 12.0 + (requested_seconds / 60.0) * (2.2 if decoder_mode == "full" else 0.35)
        headroom = min(free_gib, budget_gib)
        if estimate_gib <= headroom:
            return None
        return {
            "level": "warning",
            "message": (
                f"Estimated peak of about {estimate_gib:.0f} GiB for {requested_seconds:.0f}s with the "
                f"{decoder_mode} decoder, against {headroom:.0f} GiB available. This is an estimate; the "
                "request will run unchanged and will report CUDA_OOM if it does not fit."
            ),
            "estimate_gib": round(estimate_gib, 1),
            "available_gib": round(headroom, 1),
        }
