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
            try:
                processes = [
                    {"pid": int(p.pid), "used_bytes": int(p.usedGpuMemory or 0)}
                    for p in pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                ]
            except Exception:
                processes = []
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
                    "processes": processes,
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

    def devices(self) -> dict:
        """Selectable GPUs, merging what NVML sees with what the worker reports.

        NVML in the API process sees every physical card. The worker may see a
        subset, because CUDA_VISIBLE_DEVICES remaps indices. Where the worker
        has reported its own view, that view is authoritative for selection —
        an index the worker cannot address is not a real choice.
        """
        physical, driver, error = _gpus()
        state = self.worker_state()
        worker = next((entry for entry in state["workers"] if entry.get("online")), None)
        reported = (worker or {}).get("gpu", {}).get("devices")
        selected = self.store.device_index()
        worker_pids = {entry.get("pid") for entry in state["workers"] if entry.get("pid")}

        if reported:
            # Worker indices equal NVML indices only when CUDA_VISIBLE_DEVICES
            # is unset. When it is set the mapping is unknown, so live
            # utilisation and process data are simply not merged rather than
            # attributed to the wrong card — two identical A6000s are easy to
            # confuse and a wrong attribution is worse than a missing one.
            by_index = {device["index"]: device for device in physical}
            mergeable = self.settings.cuda_visible_devices is None
            devices = []
            for entry in reported:
                match = by_index.get(entry["index"]) if mergeable else None
                merged = {
                    "index": entry["index"],
                    "name": entry.get("name"),
                    "memory_total_bytes": entry.get("total_bytes"),
                    "memory_free_bytes": entry.get("free_bytes"),
                    "memory_used_bytes": (entry.get("total_bytes") or 0) - (entry.get("free_bytes") or 0),
                    "compute_capability": entry.get("compute_capability"),
                    "bf16_supported": entry.get("bf16_supported"),
                    "utilisation_percent": (match or {}).get("utilisation_percent"),
                    "temperature_c": (match or {}).get("temperature_c"),
                    "processes": (match or {}).get("processes", []),
                    "reported_by": "worker",
                    "live_stats": match is not None,
                }
                merged["other_process_count"] = sum(
                    1 for process in merged["processes"] if process["pid"] not in worker_pids
                )
                merged["other_process_bytes"] = sum(
                    process["used_bytes"] for process in merged["processes"] if process["pid"] not in worker_pids
                )
                merged["selected"] = merged["index"] == selected
                devices.append(merged)
        else:
            devices = []
            for entry in physical:
                device = dict(entry)
                device["reported_by"] = "nvml"
                device["bf16_supported"] = None
                device["other_process_count"] = len(device.get("processes", []))
                device["other_process_bytes"] = sum(p["used_bytes"] for p in device.get("processes", []))
                device["selected"] = device["index"] == selected
                devices.append(device)

        active = (worker or {}).get("gpu", {}).get("active_index")
        return {
            "devices": devices,
            "selected_index": selected,
            "active_index": active,
            "pending_restart": active is not None and active != selected,
            "worker_online": state["online"],
            "driver_version": driver,
            "error": error,
            "cuda_visible_devices": self.settings.cuda_visible_devices,
            "note": (
                "CUDA_VISIBLE_DEVICES is set, so the worker only sees a subset of the machine's GPUs "
                "and its indices are renumbered. Unset it to choose freely."
                if self.settings.cuda_visible_devices
                else None
            ),
        }

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
            "devices": self.devices(),
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
