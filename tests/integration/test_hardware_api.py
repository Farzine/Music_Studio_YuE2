"""Hardware API contracts with remapped devices and stopped workers."""
from datetime import datetime, timezone
import json

from app.core.deps import store_provider
from app.services import system_info


def write_worker(*, state="idle", devices=None):
    store = store_provider()
    directory = store.root / "worker"
    directory.mkdir(exist_ok=True)
    (directory / "test.json").write_text(json.dumps(dict(
        updated_at=datetime.now(timezone.utc).isoformat(), state=state,
        gpu=dict(available=True, devices=devices or [], active_index=0),
        runtime={"cuda": "12.6"}, model={"loaded": True, "device_index": 0, "model": "model"})))


def test_hardware_scan_ram_and_worker_gpu_selection(api_client, monkeypatch):
    monkeypatch.setattr(system_info, "_gpus", lambda: ([], None, None))
    write_worker(devices=[dict(index=0, uuid="GPU-1", name="Card", total_bytes=100,
                              free_bytes=50, compute_capability="8.9")])
    response = api_client.get("/api/v1/system/info")
    assert response.status_code == 200
    body = response.json()
    assert {"total_bytes", "available_bytes", "used_bytes", "source", "logical_cpu_count"} <= body["memory"].keys()
    assert body["devices"]["devices"][0]["cuda_runtime"] == "12.6"
    # Legacy heartbeat remains useful for display, but cannot acknowledge a switch.
    assert api_client.put("/api/v1/system/device", json={"device_index": 0}).status_code == 409
    assert api_client.put("/api/v1/system/device", json={"device_index": 1}).status_code == 422


def test_stopped_worker_is_not_ready_or_loaded(api_client, monkeypatch):
    monkeypatch.setattr(system_info, "_gpus", lambda: ([], None, None))
    write_worker(state="stopped", devices=[dict(index=0, total_bytes=100, free_bytes=50)])
    body = api_client.get("/api/v1/system/info").json()
    assert not body["worker"]["online"]
    assert body["devices"]["active_index"] is None
    assert body["devices"]["devices"] == []
    assert not api_client.get("/api/v1/health").json()["worker_online"]


def test_offline_physical_gpu_cannot_be_mistaken_for_cuda_index(api_client, monkeypatch):
    monkeypatch.setattr(system_info, "_gpus", lambda: ([dict(index=0, uuid="GPU-0", name="Card",
                                                          memory_total_bytes=100, processes=[])], "driver", None))
    body = api_client.get("/api/v1/system/gpus").json()
    assert body["devices"][0]["cuda_available"] is None
    assert api_client.put("/api/v1/system/device", json={"device_index": 0}).status_code == 422
