"""Hardware facts use no real GPU and never import torch in the API."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import socket
import sys
from types import SimpleNamespace

import pytest

from yue2_studio_core.hardware import precision_capabilities, system_memory
from yue2_studio_core.queue import FilesystemJobQueue
from yue2_studio_core.settings import Settings
from app.services import system_info
from app.services.capabilities import CapabilityService
from services.yue2_worker.worker import gpu_snapshot


def service(store):
    return system_info.SystemInfoService(store.settings, store, FilesystemJobQueue(store))


def heartbeat(store, **overrides):
    directory = store.root / "worker"
    directory.mkdir(exist_ok=True)
    payload = dict(state="idle", updated_at=datetime.now(timezone.utc).isoformat(), gpu={})
    payload.update(overrides)
    (directory / "test.json").write_text(json.dumps(payload))


@pytest.mark.parametrize("overrides", [
    {"state": "stopped"}, {"state": "failed"},
    {"updated_at": "bad"}, {"updated_at": "2026-09-30T12:00:00"},
    {"updated_at": 123},
    {"updated_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
    {"updated_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()},
])
def test_invalid_or_stopped_heartbeat_is_offline(store, overrides):
    heartbeat(store, **overrides)
    assert not service(store).worker_state()["online"]


def test_malformed_worker_document_cannot_crash_scan(store):
    heartbeat(store, gpu=[])
    assert not service(store).worker_state()["online"]
    heartbeat(store, gpu={"devices": [None]})
    assert not service(store).worker_state()["online"]


def test_dead_local_process_is_offline(store, monkeypatch):
    heartbeat(store, pid=123, hostname=socket.gethostname())
    def absent(*args):
        raise ProcessLookupError()
    monkeypatch.setattr(system_info.os, "kill", absent)
    assert not service(store).worker_state()["online"]
    heartbeat(store, pid=123, hostname="remote-worker-host")
    assert service(store).worker_state()["online"]  # API cannot test remote PIDs.


def test_remapped_identical_gpus_merge_only_by_uuid(store, monkeypatch):
    physical = [dict(index=i, uuid=f"GPU-{i}", name="identical card", memory_total_bytes=100,
                     memory_used_bytes=20+i, memory_free_bytes=80-i, processes=[], utilisation_percent=i)
                for i in range(2)]
    monkeypatch.setattr(system_info, "_gpus", lambda: (physical, "driver", None))
    heartbeat(store, gpu=dict(available=True, active_index=0, cuda_visible_devices="1,0", devices=[
        dict(index=0, uuid="GPU-1", total_bytes=100, free_bytes=50, compute_capability="8.9"),
        dict(index=1, uuid="GPU-0", total_bytes=100, free_bytes=40, compute_capability="7.5")]),
        runtime={"cuda": "12.6"}, model={"loaded": True, "device_index": 0, "model": "selected"})
    answer = service(store).devices()
    assert [d["physical_index"] for d in answer["devices"]] == [1, 0]
    assert [d["memory_free_bytes"] for d in answer["devices"]] == [79, 80]
    assert [d["loaded_model"] for d in answer["devices"]] == ["selected", None]
    assert answer["cuda_visible_devices"] == "1,0"
    store.write_runtime_settings({"device_index": 1})
    probe = CapabilityService(store.settings, store).runtime_probe()
    assert probe["compute_capability"] == (7, 5)
    assert probe["device_index"] == 1
    assert not CapabilityService(store.settings, store).capabilities("native")["capabilities"]["quantization_fp8"]["supported"]


def test_unknown_identity_does_not_merge_by_index_or_name(store, monkeypatch):
    monkeypatch.setattr(system_info, "_gpus", lambda: ([dict(index=0, name="card", uuid="GPU-0")], "driver", None))
    heartbeat(store, gpu=dict(available=True, devices=[dict(index=0, name="card", total_bytes=100, free_bytes=None)]))
    device = service(store).devices()["devices"][0]
    assert not device["live_stats"]
    assert device["physical_index"] is None
    assert device["memory_used_bytes"] is None
    assert device["other_process_count"] is None
    assert service(store).model_recommendation()["recommended"] is None


def test_offline_physical_cards_are_not_cuda_choices(store, monkeypatch):
    monkeypatch.setattr(system_info, "_gpus", lambda: ([dict(index=0, uuid="GPU-0", memory_total_bytes=100,
                                                           memory_free_bytes=90, processes=[])], "driver", None))
    answer = service(store).devices()
    assert answer["cuda_available"] is None
    assert not answer["devices"][0]["selectable"]
    assert not answer["devices"][0]["selected"]
    assert service(store).vram_risk(600, "full", 40) is None
    heartbeat(store, gpu={"available": False, "devices": []})
    assert service(store).devices()["devices"] == []  # Do not offer hidden physical cards.


def test_vram_warning_uses_selected_gpu(store, monkeypatch):
    instance = service(store)
    monkeypatch.setattr(instance, "devices", lambda: dict(selected_index=1, devices=[
        dict(index=0, memory_free_bytes=50*2**30), dict(index=1, memory_free_bytes=2*2**30)]))
    assert instance.vram_risk(60, "tiled", 40)["available_gib"] == 2


def test_ram_reports_memavailable_not_memfree(monkeypatch):
    monkeypatch.setattr(system_info.Path, "read_text", lambda *a, **k: "MemTotal: 1000 kB\nMemFree: 10 kB\nMemAvailable: 400 kB\n")
    facts = system_memory()
    assert facts["available_bytes"] == 400*1024
    assert facts["used_bytes"] == 600*1024
    monkeypatch.setattr(system_info.Path, "read_text", lambda *a, **k: "MemTotal: 1000 kB\nMemFree: 10 kB\n")
    assert system_memory()["available_bytes"] is None


def test_ram_fallback_does_not_invent_available_memory(monkeypatch):
    def absent(*args, **kwargs):
        raise OSError()
    monkeypatch.setattr(system_info.Path, "read_text", absent)
    monkeypatch.setattr(system_info.os, "sysconf", lambda name: 1024)
    assert system_memory()["total_bytes"] == 1024**2
    assert system_memory()["available_bytes"] is None


def test_worker_checks_each_precision_in_its_device_context(monkeypatch):
    current = [1]
    @contextmanager
    def device(index):
        previous = current[0]
        current[0] = index
        yield
        current[0] = previous
    cuda = SimpleNamespace(is_available=lambda: True, current_device=lambda: current[0], device_count=lambda: 2,
        device=device, get_device_properties=lambda i: SimpleNamespace(name="card", uuid=f"GPU-{i}",
                                                                      major=7 if i == 0 else 8, minor=5 if i == 0 else 9),
        mem_get_info=lambda i: (80, 100), is_bf16_supported=lambda including_emulation: current[0] == 1,
        memory_allocated=lambda i: i+1, memory_reserved=lambda i: i+10, max_memory_allocated=lambda i: 20)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1,0")
    facts = gpu_snapshot(1)
    assert [d["bf16_supported"] for d in facts["devices"]] == [False, True]
    assert facts["devices"][1]["uuid"] == "GPU-1"
    assert facts["devices"][1]["allocated_bytes"] == 2
    assert current[0] == 1
    assert gpu_snapshot(31)["active_index"] is None
    original = cuda.get_device_properties
    def broken_card(index):
        if index == 0:
            raise RuntimeError("card unavailable")
        return original(index)
    cuda.get_device_properties = broken_card
    partial = gpu_snapshot(0)
    assert partial["available"]
    assert partial["devices"][0]["error"] == "card unavailable"
    assert partial["devices"][1]["uuid"] == "GPU-1"
    cuda.is_available = lambda: False
    assert gpu_snapshot()["available"] is False


def test_nvml_unsupported_sensors_preserve_other_facts(monkeypatch):
    shutdown = []
    def unsupported(*args):
        raise RuntimeError("unsupported")
    nvml = SimpleNamespace(nvmlInit=lambda: None, nvmlShutdown=lambda: shutdown.append(True),
        nvmlSystemGetDriverVersion=lambda: b"driver", nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda i: i, nvmlDeviceGetName=lambda h: b"card",
        nvmlDeviceGetMemoryInfo=lambda h: SimpleNamespace(total=100, used=20, free=80),
        nvmlDeviceGetCudaComputeCapability=unsupported, nvmlDeviceGetUUID=lambda h: b"GPU-0",
        nvmlDeviceGetPciInfo=lambda h: SimpleNamespace(busId=b"0000:01:00.0"),
        nvmlDeviceGetUtilizationRates=unsupported, nvmlDeviceGetTemperature=unsupported,
        nvmlDeviceGetComputeRunningProcesses=lambda h: [SimpleNamespace(pid=2, usedGpuMemory=2**64-1)])
    monkeypatch.setitem(sys.modules, "pynvml", nvml)
    devices, driver, error = system_info._gpus()
    assert error is None and driver == "driver"
    assert devices[0]["memory_total_bytes"] == 100
    assert devices[0]["bf16_supported"] is None
    assert devices[0]["processes"][0]["used_bytes"] is None
    assert shutdown == [True]
    nvml.nvmlDeviceGetCount = lambda: 2
    nvml.nvmlDeviceGetHandleByIndex = lambda i: i if i else unsupported()
    assert len(system_info._gpus()[0]) == 2
    nvml.nvmlInit = unsupported
    assert system_info._gpus()[0] == []


def test_precision_thresholds_are_hardware_eligibility():
    assert precision_capabilities(None)["fp16_supported"] is None
    assert not precision_capabilities((5, 2))["fp16_supported"]
    assert precision_capabilities((5, 3))["fp16_supported"]
    assert not precision_capabilities((7, 5))["bf16_supported"]
    assert precision_capabilities((8, 0))["bf16_supported"]
    assert not precision_capabilities((8, 6))["fp8_supported"]
    assert precision_capabilities((8, 9))["fp8_supported"]
