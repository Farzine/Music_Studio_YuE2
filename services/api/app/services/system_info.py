"""GPU, disk, worker and queue state for the System page.

GPU numbers come from NVML. Runtime versions and model residency come from the
worker's heartbeat file, because the API process deliberately does not import
torch or the YuE2 runtime.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yue2_studio_core.models import JobStatus
from yue2_studio_core.hardware import precision_capabilities, system_memory
from yue2_studio_core.queue import FilesystemJobQueue
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store

HEARTBEAT_STALE_AFTER = timedelta(seconds=30)

# Published longform peak VRAM on an RTX 5090; leave 20% or 1 GiB of
# headroom, whichever is larger. ponytail: benchmark-based estimate; replace
# with per-device observed peaks when enough real runs have been collected.
GGUF_VARIANTS = (
    ("Q4_0", "yue2-3b-q4_0.gguf", 2_665_632_320, 7_755),
    ("Q8_0", "yue2-3b-q8_0.gguf", 4_264_186_432, 8_867),
    ("BF16", "yue2-3b-bf16.gguf", 7_261_475_392, 12_535),
)


def _optional(probe):
    """An unsupported sensor must not hide all the other hardware facts."""
    try:
        value = probe()
        return value.decode() if isinstance(value, bytes) else value
    except Exception:
        return None


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
        driver = _optional(pynvml.nvmlSystemGetDriverVersion)
        devices = []
        for index in range(pynvml.nvmlDeviceGetCount()):
            handle = _optional(lambda: pynvml.nvmlDeviceGetHandleByIndex(index))
            if handle is None:
                devices.append({"index": index, "name": None, "error": "GPU handle is unavailable.",
                                "uuid": None, "pci_bus_id": None, "driver_version": driver,
                                "memory_total_bytes": None, "memory_free_bytes": None, "memory_used_bytes": None,
                                "compute_capability": None, "utilisation_percent": None, "temperature_c": None,
                                "processes": None,
                                **precision_capabilities(None)})
                continue
            name = _optional(lambda: pynvml.nvmlDeviceGetName(handle))
            memory = _optional(lambda: pynvml.nvmlDeviceGetMemoryInfo(handle))
            capability = _optional(lambda: pynvml.nvmlDeviceGetCudaComputeCapability(handle))
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
                    {"pid": int(p.pid), "used_bytes": (
                        int(p.usedGpuMemory) if p.usedGpuMemory is not None
                        and p.usedGpuMemory != 2**64 - 1 else None)}
                    for p in pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                ]
            except Exception:
                processes = None
            devices.append(
                {
                    "index": index,
                    "name": name,
                    "uuid": _optional(lambda: pynvml.nvmlDeviceGetUUID(handle)),
                    "pci_bus_id": _optional(lambda: pynvml.nvmlDeviceGetPciInfo(handle).busId),
                    "driver_version": driver,
                    "memory_total_bytes": int(memory.total) if memory else None,
                    "memory_used_bytes": int(memory.used) if memory else None,
                    "memory_free_bytes": int(memory.free) if memory else None,
                    "compute_capability": f"{capability[0]}.{capability[1]}" if capability else None,
                    **precision_capabilities(tuple(capability) if capability else None),
                    "utilisation_percent": utilisation,
                    "temperature_c": temperature,
                    "processes": processes,
                }
            )
        return devices, driver, None
    except Exception as exc:
        return [], None, f"GPU scan failed: {exc}"
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
                except (OSError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if any(not isinstance(payload.get(key, {}), dict) for key in ("gpu", "runtime", "model")):
                    continue
                reported = payload.get("gpu", {}).get("devices", [])
                if not isinstance(reported, list) or any(
                    not isinstance(device, dict) or type(device.get("index")) is not int or device["index"] < 0
                    for device in reported
                ):
                    continue
                seen = payload.get("updated_at")
                stale = True
                if seen:
                    try:
                        age = datetime.now(timezone.utc) - datetime.fromisoformat(seen)
                        stale = not timedelta(seconds=-5) <= age <= HEARTBEAT_STALE_AFTER
                    except (ValueError, TypeError):
                        stale = True
                alive = None
                if payload.get("hostname") == socket.gethostname():
                    pid = payload.get("pid")
                    if type(pid) is int and pid > 0:
                        try:
                            os.kill(pid, 0)
                            alive = True
                        except ProcessLookupError:
                            alive = False
                        except OverflowError:
                            alive = False
                        except PermissionError:
                            alive = True
                payload["process_alive"] = alive
                payload["stale"] = stale
                payload["online"] = not stale and payload.get("state") in ("starting", "idle", "busy") and alive is not False
                workers.append(payload)
        return {"workers": workers, "online": any(worker["online"] for worker in workers)}

    def devices(self, *, physical_probe=None, state=None) -> dict:
        """Selectable GPUs, merging what NVML sees with what the worker reports.

        NVML in the API process sees every physical card. The worker may see a
        subset, because CUDA_VISIBLE_DEVICES remaps indices. Where the worker
        has reported its own view, that view is authoritative for selection —
        an index the worker cannot address is not a real choice.
        """
        physical, driver, error = physical_probe if physical_probe is not None else _gpus()
        state = state if state is not None else self.worker_state()
        worker = next((entry for entry in state["workers"] if entry.get("online")), None)
        reported = (worker or {}).get("gpu", {}).get("devices")
        selected = self.store.device_index()
        worker_pids = {entry.get("pid") for entry in state["workers"] if entry.get("online") and entry.get("pid")}
        gpu = (worker or {}).get("gpu", {})

        if worker is not None:
            # Logical CUDA indices may differ from physical NVML indices even
            # without a visibility mask. Only stable identity permits a merge.
            by_uuid = {device["uuid"]: device for device in physical if device.get("uuid")}
            devices = []
            for entry in reported or []:
                match = by_uuid.get(entry.get("uuid"))
                total = (match or {}).get("memory_total_bytes")
                free = (match or {}).get("memory_free_bytes")
                total = entry.get("total_bytes") if total is None else total
                free = entry.get("free_bytes") if free is None else free
                merged = {
                    "index": entry["index"],
                    "error": entry.get("error"),
                    "name": entry.get("name"),
                    "uuid": entry.get("uuid"),
                    "physical_index": (match or {}).get("index"),
                    "pci_bus_id": (match or {}).get("pci_bus_id"),
                    "driver_version": driver if match else None,
                    "cuda_available": gpu.get("available"),
                    "cuda_runtime": (worker.get("runtime") or {}).get("cuda"),
                    "memory_total_bytes": total,
                    "memory_free_bytes": free,
                    "memory_used_bytes": total - free if total is not None and free is not None else None,
                    "compute_capability": entry.get("compute_capability"),
                    "bf16_supported": entry.get("bf16_supported"),
                    "fp16_supported": entry.get("fp16_supported"),
                    "fp8_supported": entry.get("fp8_supported"),
                    "precision_source": entry.get("precision_source", "unknown"),
                    "allocated_bytes": entry.get("allocated_bytes"),
                    "reserved_bytes": entry.get("reserved_bytes"),
                    "loaded_model": (worker.get("model") or {}).get("model") if (
                        (worker.get("model") or {}).get("loaded")
                        and (worker.get("model") or {}).get("device_index") == entry["index"]
                    ) else None,
                    "utilisation_percent": (match or {}).get("utilisation_percent"),
                    "temperature_c": (match or {}).get("temperature_c"),
                    "processes": (match or {}).get("processes"),
                    "reported_by": "worker",
                    "live_stats": match is not None,
                    "memory_source": "nvml" if match and match.get("memory_free_bytes") is not None else "worker_heartbeat",
                    "selectable": True,
                    "stats_updated_at": (datetime.now(timezone.utc).isoformat()
                                         if match and match.get("memory_free_bytes") is not None else worker.get("updated_at")),
                }
                merged["selected"] = merged["index"] == selected
                devices.append(merged)
        else:
            devices = []
            for entry in physical:
                device = dict(entry)
                device["reported_by"] = "nvml"
                device.update(physical_index=device["index"], cuda_available=None, cuda_runtime=None,
                              loaded_model=None, allocated_bytes=None, reserved_bytes=None,
                              selectable=False, selected=False, live_stats=True,
                              memory_source="nvml",
                              stats_updated_at=datetime.now(timezone.utc).isoformat())
                devices.append(device)

        for device in devices:
            processes = device.get("processes")
            other = [p for p in processes if p["pid"] not in worker_pids] if processes is not None else None
            device["other_process_count"] = len(other) if other is not None else None
            device["other_process_bytes"] = (sum(p["used_bytes"] for p in other)
                                             if other is not None and all(p.get("used_bytes") is not None for p in other) else None)

        active = (worker or {}).get("gpu", {}).get("active_index")
        return {
            "devices": devices,
            "selected_index": selected,
            "active_index": active,
            "pending_restart": active is not None and active != selected,
            "worker_online": state["online"],
            "driver_version": driver,
            "error": error,
            "cuda_available": gpu.get("available") if worker else None,
            "cuda_visible_devices": gpu.get("cuda_visible_devices") if worker else None,
            "note": (
                "CUDA_VISIBLE_DEVICES is set, so the worker only sees a subset of the machine's GPUs "
                "and its indices are renumbered. Unset it to choose freely."
                if gpu.get("cuda_visible_devices")
                else "Worker offline: physical GPU indices are informational; start the worker to confirm selectable CUDA devices." if worker is None else gpu.get("error")
            ),
        }

    def model_recommendation(self) -> dict:
        inventory = self.devices()
        selected = next((item for item in inventory["devices"] if item["index"] == inventory["selected_index"]), None)
        if not selected or not selected.get("selectable", True) or not selected.get("memory_total_bytes") or selected.get("memory_free_bytes") is None:
            return {"device_index": inventory["selected_index"], "available_bytes": None,
                    "variants": [], "recommended": None, "max_model_bytes": None,
                    "max_parameters": None, "note": "GPU memory is unavailable; a recommendation cannot be calculated."}
        worker_pids = {entry.get("pid") for entry in self.worker_state()["workers"] if entry.get("online")}
        own_bytes = sum(p["used_bytes"] or 0 for p in selected.get("processes") or [] if p["pid"] in worker_pids)
        available = int(selected["memory_free_bytes"] or 0) + own_bytes
        variants = []
        for label, filename, size, peak_mib in GGUF_VARIANTS:
            peak = peak_mib * 1024**2
            required = int(max(peak * 1.2, peak + 1024**3))
            variants.append({
                "label": label, "repo_id": "audio-cpp/Yue2-3B-GGUF", "filename": filename,
                "model_bytes": size, "parameters": 3_000_000_000, "peak_bytes": peak,
                "required_bytes": required, "runnable": available >= required,
            })
        recommended = next((item for item in reversed(variants) if item["runnable"]), None)
        return {"device_index": selected["index"], "available_bytes": available,
                "variants": variants, "recommended": recommended,
                "max_model_bytes": recommended["model_bytes"] if recommended else None,
                "max_parameters": recommended["parameters"] if recommended else None,
                "note": "Conservative estimates from one published RTX 5090 longform benchmark; actual use varies with song length and other GPU workloads."}

    def info(self) -> dict:
        physical_probe = _gpus()
        devices, driver, gpu_error = physical_probe
        state = self.worker_state()
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
            "memory": system_memory(),
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
            "worker": state,
            "devices": self.devices(physical_probe=physical_probe, state=state),
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
        inventory = self.devices()
        device = next((d for d in inventory["devices"] if d["index"] == inventory["selected_index"]), None)
        if device is None or not device.get("selectable", True) or device.get("memory_free_bytes") is None:
            return None
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
