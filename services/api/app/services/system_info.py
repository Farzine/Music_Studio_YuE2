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

from yue2_studio_core.hardware import precision_capabilities, system_memory
from yue2_studio_core.model_metadata import ModelMetadata, audiocpp_available, resolve_model_reference, resolve_vae_reference
from yue2_studio_core.model_recommendations import assess_model, gpu_capacity, sort_recommendations
from yue2_studio_core.errors import ConflictError, UnsupportedCapabilityError, ValidationError
from yue2_studio_core.runtime_commands import RuntimeCommands
from yue2_studio_core.queue import FilesystemJobQueue
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store

HEARTBEAT_STALE_AFTER = timedelta(seconds=30)

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
        online = [entry for entry in state["workers"] if entry.get("online")]
        worker = next((entry for entry in online if entry.get("worker_id") == self.settings.worker_id), next(iter(online), None))
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
                    "worker_busy": bool(worker.get("current_generation_id") or worker.get("state") == "busy"),
                    "loaded_vae": (worker.get("model") or {}).get("vae") if (
                        (worker.get("model") or {}).get("loaded")
                        and (worker.get("model") or {}).get("device_index") == entry["index"]
                        and ("vae_gpu_resident" not in worker.get("model", {}) or worker["model"].get("vae_gpu_resident") is True)
                    ) else None,
                    "loaded_model": (worker.get("model") or {}).get("model") if (
                        (worker.get("model") or {}).get("loaded")
                        and (worker.get("model") or {}).get("device_index") == entry["index"]
                        and ("model_gpu_resident" not in worker.get("model", {}) or worker["model"].get("model_gpu_resident") is True)
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
        commands = [c for c in RuntimeCommands(self.store).list()
                    if c.worker_id == self.settings.worker_id and c.operation == "select_device"]
        latest = max(commands, key=lambda c: (c.created_at, c.id), default=None)
        switch_command = latest.model_dump(mode="json") if latest else None
        if switch_command is not None:
            switch_command["worker_online"] = any(entry.get("online") and entry.get("worker_id") == latest.worker_id
                                                   and entry.get("session_id") == latest.worker_session for entry in state["workers"])
        return {
            "devices": devices,
            "selected_index": selected,
            "active_index": active,
            "pending_restart": active is not None and active != selected,
            "switch_command": switch_command,
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

    def select_device(self, device_index: int) -> dict:
        """Admission only: the serial worker owns placement and selection commit."""
        with self.store.queue_lock():
            RuntimeCommands(self.store).assert_accepting_locked(self.settings.worker_id)
            state = self.worker_state()
            available = self.devices(state=state)
            indices = {d["index"] for d in available["devices"] if d.get("selectable")}
            if device_index not in indices:
                raise ValidationError(f"GPU {device_index} is unavailable to the worker. Start the worker and choose a reported CUDA index.", details={"available": sorted(indices)})
            worker = next((w for w in state["workers"] if w.get("online") and w.get("worker_id") == self.settings.worker_id), None)
            if not worker or not worker.get("session_id") or not worker.get("runtime_capabilities", {}).get("select_device_commands"):
                raise ConflictError("Start an updated GPU worker before requesting a coordinated device switch.")
            if worker.get("backend") != "native":
                raise UnsupportedCapabilityError("GPU switching requires the native worker; remote Comfy workers manage their own devices.")
            model = worker.get("model", {})
            references = [ref for ref in (model.get("model"), model.get("vae")) if ref]
            command = RuntimeCommands(self.store).enqueue_locked(worker_id=worker["worker_id"], worker_session=worker["session_id"],
                              operation="select_device", device_index=device_index, protected_references=references)
            return {**available, "switch_command": {**command.model_dump(mode="json"), "worker_online": True}}

    def model_recommendation(self, *, device_index: int | None = None, vae: str = "standard",
                             offload_ar: bool = False, compute_backend: str = "torch",
                             memory_budget_gib: float = 40, entries: list[dict] | None = None,
                             candidate_contexts: dict[str, dict] | None = None) -> dict:
        # Import locally: capabilities also consumes hardware facts, but the
        # inventory/runtime prerequisite rules remain owned by that service.
        from app.services.capabilities import CapabilityService

        state = self.worker_state()
        inventory = self.devices(state=state)
        selected_index = inventory["selected_index"] if device_index is None else device_index
        if device_index is not None and not any(d["index"] == device_index for d in inventory["devices"]):
            raise ValidationError(f"GPU {device_index} is not present in the worker hardware inventory.")
        models = [ModelMetadata.model_validate(entry) for entry in (
            entries if entries is not None else CapabilityService(self.settings, self.store).local_models())]
        vae_reference = resolve_vae_reference(vae, self.settings)
        decoder = next((m for m in models if m.role == "vae" and vae_reference in [m.id, *m.aliases]), None)
        worker = next((w for w in state["workers"] if w.get("online")), {})
        versions = worker.get("runtime", {})
        runtime = {"backend": worker.get("backend"), "audiocpp_available": audiocpp_available(self.settings),
                   "native_available": bool(versions.get("torch") and versions.get("yue2-infer"))}
        memory = system_memory()
        capacities, by_gpu = [], []
        for device in inventory["devices"]:
            capacity = gpu_capacity(device, self.settings)
            capacities.append(capacity)
            items = sort_recommendations([
                assess_model(m, device=device, capacity=capacity, vae=decoder, settings=self.settings,
                             runtime=runtime, ram=memory, offload_ar=offload_ar,
                             compute_backend=compute_backend, memory_budget_gib=memory_budget_gib,
                             **(candidate_contexts or {}).get(m.id, {}))
                for m in models if m.role == "model"
            ])
            by_gpu.append({"device_index": device["index"], "items": items})
        selected = next((c for c in capacities if c["device_index"] == selected_index), None)
        items = next((g["items"] for g in by_gpu if g["device_index"] == selected_index), [])
        recommended = next((item for item in items if item["runnable"]), None)
        return {"device_index": selected_index, "available_bytes": selected["available_bytes"] if selected else None,
                "capacities": capacities, "items": items, "by_gpu": by_gpu, "variants": items,
                "recommended": recommended,
                "max_model_bytes": selected["comfortable_model_bytes"] if selected else None,
                "max_parameters": None,  # No universal parameter count independent of precision/architecture.
                "memory": memory,
                "scenario": {"vae": vae_reference, "offload_ar": offload_ar,
                             "compute_backend": compute_backend, "memory_budget_gib": memory_budget_gib},
                "policy": {key: getattr(self.settings, key) for key in (
                    "model_vram_safety_fraction", "model_vram_safety_gib", "model_runtime_overhead_gib",
                    "model_unknown_kv_gib", "model_unknown_vae_gib", "model_weight_overhead_factor")},
                "note": "Planning estimates, not load guarantees. Capacity is heuristic; model estimates use available metadata. "
                        "Idle resident memory is reclaimable only after unloading; active allocations stay reserved."}

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

    def vram_risk(self, requested_seconds: float, decoder_mode: str, budget_gib: float,
                  *, model: str = "default", vae: str = "standard", offload_ar: bool = False,
                  compute_backend: str = "torch") -> dict | None:
        """Project the same model estimate into the existing task warning API."""
        recommendation = self.model_recommendation(vae=vae, offload_ar=offload_ar,
                                                  compute_backend=compute_backend, memory_budget_gib=budget_gib)
        reference = resolve_model_reference(model, self.settings)
        item = next((m for m in recommendation["items"] if reference in [m["id"], *m.get("aliases", [])]), None)
        if item is None or item["safe_budget_bytes"] is None or item["peak_bytes"] is None:
            return None
        estimate = item["peak_bytes"] / 2**30
        available = item["safe_budget_bytes"] / 2**30
        if decoder_mode != "full" and not item["excess_bytes"]:
            return None
        message = (f"Estimated model/VAE/cache/runtime VRAM is {estimate:.1f} GiB against a safe budget of "
                   f"{available:.1f} GiB on GPU {recommendation['device_index']}. "
                   "Cache uses full declared context (or a configured reserve), not an exact duration peak. ")
        if decoder_mode == "full":
            message += f"Full waveform decoding for {requested_seconds:.0f}s needs additional unprofiled memory; the tiled estimate cannot confirm it. "
        return {"level": "warning", "message": message + "This estimate does not change your request.",
                "estimate_gib": round(estimate, 1), "available_gib": round(available, 1)}
