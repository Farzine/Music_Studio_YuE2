"""Download boundaries and the hardware estimate, without network or GPU."""
from __future__ import annotations

from types import SimpleNamespace
from contextlib import nullcontext
import sys
import errno
import hashlib
import json
import struct
from pathlib import Path

import pytest

from yue2_studio_core.errors import ConflictError, ValidationError
from yue2_studio_core.model_files import model_file_leases
from yue2_studio_core.queue import FilesystemJobQueue
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store

from app.services.model_downloads import ModelDownloads
from app.services.system_info import SystemInfoService
from services.yue2_worker.model_manager.manager import ModelManager
from yue2_studio_core.models import GenerationConfig


def manager(tmp_path):
    settings = Settings(data_dir=str(tmp_path / "data"), yue2_models_dir=str(tmp_path / "models"),
                        yue2_model_path=str(tmp_path / "models" / "default"), yue2_vae_path=str(tmp_path / "models" / "vae"),
                        yue2_vae_legacy_path=str(tmp_path / "models" / "legacy"))
    return ModelDownloads(settings, Store(settings))


def test_api_shutdown_fails_queued_download_but_preserves_live_transfer(tmp_path, download_package):
    from yue2_studio_core.store import file_lock
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", "main")
    with file_lock(downloads.root / f".{job['id']}.run.lock"):
        downloads.shutdown()
        assert downloads.get(job["id"])["status"] == "queued"
    downloads.shutdown()
    stopped = downloads.get(job["id"])
    assert stopped["status"] == "failed" and stopped["registry_id"] is None
    assert "API stopped" in stopped["error"]
    assert downloads.retry(job["id"])["status"] == "queued"


def test_gguf_download_is_registered_only_after_verification(tmp_path, monkeypatch, download_package):
    downloads = manager(tmp_path)
    with pytest.raises(ValidationError):
        downloads.start("owner/repository", "../escape.gguf", None)
    job = downloads.start("owner/repository", "custom.gguf", "main")
    assert job["status"] == "queued"
    downloads.run(job["id"])
    complete = downloads.get(job["id"])
    assert complete["status"] == "complete", complete
    assert complete["validation_status"] == "validated" and complete["registry_id"]
    entry = next(item for item in downloads.registry.inventory() if item.registry_id == complete["registry_id"])
    assert entry.inference_ready and entry.quantization == "Q4_0"
    assert entry.commit_hash == "a" * 40
    assert complete["downloaded_bytes"] == complete["total_bytes"] and complete["percentage"] == 100
    assert complete["bytes_per_second"] is None and complete["eta_seconds"] is None
    assert not downloads._stage(job).exists()


def test_failed_transfer_does_not_register_partial_weights(tmp_path, monkeypatch, download_package):
    downloads = manager(tmp_path)
    def interrupted(repo_id, filename, *, revision, local_dir, callback, force_download=False):
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / (filename + ".part")).write_bytes(b"partial")
        raise OSError("Network interrupted")
    monkeypatch.setattr("app.services.model_downloads.download_file", interrupted)
    job = downloads.start("owner/repository", "custom.gguf", None)
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "failed"
    assert not downloads.registry.path.exists()
    assert not list(downloads.settings.models_path.rglob("studio-model.json"))
    assert downloads._stage(job).exists()


def test_recommendation_uses_selected_gpu_and_headroom(tmp_path, monkeypatch):
    settings = Settings(data_dir=str(tmp_path / "data"))
    store = Store(settings)
    service = SystemInfoService(settings, store, FilesystemJobQueue(store))
    monkeypatch.setattr(service, "devices", lambda **kw: {
        "selected_index": 1,
        "devices": [{"index": 1, "memory_total_bytes": 12 * 1024**3,
                     "memory_free_bytes": 10 * 1024**3, "processes": [],
                     "selectable": True, "cuda_available": True}],
    })
    monkeypatch.setattr(service, "worker_state", lambda: {"workers": []})
    answer = service.model_recommendation(entries=[])
    assert answer["device_index"] == 1
    assert answer["max_parameters"] is None  # capacity varies with precision
    assert answer["recommended"] is None    # do not fabricate benchmark models
    assert answer["capacities"][0]["usable_bytes"] < 10 * 1024**3
    assert answer["max_model_bytes"] > 0


def test_idle_gpu_switch_closes_the_previous_pipeline(tmp_path, monkeypatch):
    settings = Settings(data_dir=str(tmp_path / "data"))
    store = Store(settings)
    manager = ModelManager(settings, store=store)
    closed = []
    manager._pipeline = SimpleNamespace(close=lambda: closed.append(True))
    manager._key = manager.key_for(GenerationConfig())
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(
        device=lambda index: nullcontext(), empty_cache=lambda: None, ipc_collect=lambda: None,
    )))
    store.write_runtime_settings({"device_index": 1})
    assert manager.release_if_device_changed()
    assert closed == [True]
    assert not manager.loaded


@pytest.mark.parametrize("mode,expected", [("single", 6), ("selected", 1), ("repository", 9)])
def test_selection_modes_pin_files_and_keep_incomplete_distinct(tmp_path, download_package, mode, expected):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", "main", mode=mode)
    downloads.run(job["id"])
    result = downloads.get(job["id"])
    assert result["status"] == "complete", result
    assert result["total_files"] == expected
    assert all(revision == "a" * 40 for _, revision, _ in download_package.calls)
    entry = next(m for m in downloads.registry.inventory() if m.registry_id == result["registry_id"])
    assert entry.download_status == "downloaded"
    assert entry.inference_ready == (mode != "selected")
    if mode == "selected":
        assert "Missing" in entry.problem and not entry.files_complete


def test_atomic_publication_hides_staging_and_reports_real_bytes(tmp_path, download_package, monkeypatch):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "model.safetensors", None)
    observations = []
    clock = iter(range(1, 10000))
    monkeypatch.setattr("app.services.model_downloads.time.monotonic", lambda: next(clock))
    def transfer(*args, **kwargs):
        stage = kwargs["local_dir"]
        assert stage.parent.name == ".downloads"
        assert not Path(job["destination"]).exists()
        download_package.transfer(*args, **kwargs)
        assert not any(m.is_local for m in downloads.registry.inventory())
        observations.append(downloads.get(job["id"]))
    monkeypatch.setattr("app.services.model_downloads.download_file", transfer)
    history = []
    write = downloads._write
    def record(item):
        write(item)
        history.append(json.loads(json.dumps(item)))
    monkeypatch.setattr(downloads, "_write", record)
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "complete"
    assert {j["status"] for j in history} == {"downloading", "verifying", "registering", "complete"}
    assert any(j["downloaded_bytes"] > 0 and 0 < j["percentage"] < 100 for j in history)
    assert any(j["bytes_per_second"] and j["eta_seconds"] is not None for j in history if j["status"] == "downloading")
    assert observations[-1]["downloaded_bytes"] == observations[-1]["total_bytes"]


def test_retry_uses_same_commit_staging_and_preserves_cached_files(tmp_path, download_package, monkeypatch):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "model.safetensors", None)
    calls = []
    def interrupted(repo, filename, **kwargs):
        if filename == "config.json":
            partial = kwargs["local_dir"] / "config.json.part"
            partial.write_bytes(b"partial")
            raise OSError("interrupted")
        return download_package.transfer(repo, filename, **kwargs)
    monkeypatch.setattr("app.services.model_downloads.download_file", interrupted)
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "failed"
    stage = downloads._stage(job)
    before = (stage / "model.safetensors").read_bytes()
    def resumed(repo, filename, **kwargs):
        calls.append(filename)
        assert kwargs["local_dir"] == stage and kwargs["revision"] == "a" * 40
        if filename == "model.safetensors":
            assert (stage / filename).read_bytes() == before
            return str(stage / filename)  # actual SDK cache hit: no callback
        return download_package.transfer(repo, filename, **kwargs)
    monkeypatch.setattr("app.services.model_downloads.download_file", resumed)
    retry = downloads.retry(job["id"])
    assert retry["status"] == "queued" and retry["attempt"] == 2
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "complete"
    assert calls == ["model.safetensors", "config.json"]


def test_cached_installed_package_needs_no_transfer(tmp_path, download_package, monkeypatch):
    downloads = manager(tmp_path)
    first = downloads.start("owner/repository", "custom.gguf", None)
    downloads.run(first["id"])
    first = downloads.get(first["id"])
    calls_before = len(download_package.calls)
    second = downloads.start("owner/repository", "custom.gguf", None)
    downloads.run(second["id"])
    second = downloads.get(second["id"])
    assert second["status"] == "complete", second
    assert len(download_package.calls) == calls_before
    assert second["path"] == first["path"] and second["registry_id"] == first["registry_id"]
    assert second["bytes_per_second"] is None


def test_checksum_mismatch_never_publishes_and_retry_forces_invalid_file(tmp_path, download_package, monkeypatch):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "model.safetensors", None)
    def corrupt(*args, **kwargs):
        result = download_package.transfer(*args, **kwargs)
        if args[1] == "model.safetensors":
            data = Path(result).read_bytes()
            Path(result).write_bytes(data[:-1] + b"x")
        return result
    monkeypatch.setattr("app.services.model_downloads.download_file", corrupt)
    downloads.run(job["id"])
    result = downloads.get(job["id"])
    assert result["status"] == "failed" and "SHA256" in result["error"]
    assert not Path(job["destination"]).exists() and not downloads.registry.path.exists()
    monkeypatch.setattr("app.services.model_downloads.download_file", download_package.transfer)
    downloads.retry(job["id"])
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "complete"
    assert ("model.safetensors", "a" * 40, True) in download_package.calls


def test_corrupt_structure_with_matching_hash_still_fails(tmp_path, download_package):
    corrupt = b"GGUF" + struct.pack("<I", 3) + b"corrupt"
    (download_package.source / "custom.gguf").write_bytes(corrupt)
    f = next(f for f in download_package.inspection["files"] if f["name"] == "custom.gguf")
    f.update(bytes=len(corrupt), checksum_sha256=hashlib.sha256(corrupt).hexdigest())
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", None)
    downloads.run(job["id"])
    result = downloads.get(job["id"])
    assert result["status"] == "failed" and "structure" in result["error"]
    assert not downloads.registry.path.exists()


def test_registration_failure_returns_package_to_private_staging(tmp_path, download_package, monkeypatch):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "model.safetensors", None)
    from yue2_studio_core import model_registry
    original = model_registry.write_json_atomic
    def failed(path, value):
        if path == downloads.registry.path:
            raise OSError("simulated write failure")
        return original(path, value)
    monkeypatch.setattr(model_registry, "write_json_atomic", failed)
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "failed"
    assert not Path(job["destination"]).exists()
    assert (downloads._stage(job) / "model.safetensors").is_file()
    assert not any(m.is_local for m in downloads.registry.inventory())
    monkeypatch.setattr(model_registry, "write_json_atomic", original)
    downloads.retry(job["id"])
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "complete"


def test_cleanup_only_removes_private_failed_files(tmp_path, download_package, monkeypatch):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", None)
    with pytest.raises(ConflictError):
        downloads.cleanup(job["id"])
    def failed(*args, **kwargs):
        (kwargs["local_dir"] / "partial").write_bytes(b"partial")
        raise OSError("failed")
    monkeypatch.setattr("app.services.model_downloads.download_file", failed)
    stage = downloads._stage(job)
    stage.mkdir(parents=True)
    downloads.run(job["id"])
    assert stage.exists()
    result = downloads.cleanup(job["id"])
    assert not stage.exists() and result["partial_bytes"] == 0
    assert result["status"] == "failed"
    assert download_package.source.is_dir()


def test_disk_exhaustion_is_actionable_and_not_registered(tmp_path, download_package, monkeypatch):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", None)
    def failed(*args, **kwargs):
        raise OSError(errno.ENOSPC, "full")
    monkeypatch.setattr("app.services.model_downloads.download_file", failed)
    downloads.run(job["id"])
    assert "Disk became full" in downloads.get(job["id"])["error"]
    assert not downloads.registry.path.exists()


def test_active_owner_is_not_interrupted_and_dead_owner_can_retry(tmp_path, download_package, monkeypatch):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", None)
    other = ModelDownloads(downloads.settings, downloads.store)
    assert other.get(job["id"])["status"] == "queued"
    with pytest.raises(ConflictError):
        other.start("owner/repository", "custom.gguf", None)
    job["pid"] = 0
    downloads._write(job)
    interrupted = other.get(job["id"])
    assert interrupted["status"] == "failed" and "interrupted" in interrupted["error"]
    assert other.retry(job["id"])["attempt"] == 2


def test_worker_file_lease_blocks_download_publication(tmp_path, download_package):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", None)
    with model_file_leases(downloads.store, [job["destination"]]):
        downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "failed"
    assert not Path(job["destination"]).exists()


def test_staging_symlink_is_rejected_without_touching_target(tmp_path, download_package):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", None)
    stage = downloads._stage(job)
    stage.parent.mkdir(parents=True)
    stage.symlink_to(download_package.source, target_is_directory=True)
    downloads.run(job["id"])
    assert downloads.get(job["id"])["status"] == "failed"
    assert "symlink" in downloads.get(job["id"])["error"]
    with pytest.raises(ValidationError):
        downloads.cleanup(job["id"])
    assert (download_package.source / "custom.gguf").exists()


def test_full_repository_selection_does_not_replace_single_installation(tmp_path, download_package):
    downloads = manager(tmp_path)
    single = downloads.start("owner/repository", "custom.gguf", None)
    downloads.run(single["id"])
    before = (Path(single["destination"]) / "studio-model.json").read_bytes()
    whole = downloads.start("owner/repository", "custom.gguf", None, mode="repository")
    downloads.run(whole["id"])
    assert downloads.get(whole["id"])["status"] == "complete"
    assert whole["destination"] != single["destination"]
    assert (Path(single["destination"]) / "studio-model.json").read_bytes() == before


def test_abandoned_running_thread_recovers_even_when_api_pid_is_alive(tmp_path, download_package):
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", None)
    job["status"] = "verifying"
    downloads._write(job)
    assert downloads.get(job["id"])["status"] == "failed"
    assert downloads.retry(job["id"])["status"] == "queued"


def test_unknown_file_sizes_are_observed_not_guessed(tmp_path, download_package):
    for file in download_package.inspection["files"]:
        file["bytes"] = None
    downloads = manager(tmp_path)
    job = downloads.start("owner/repository", "custom.gguf", None)
    assert job["total_bytes"] is None and job["percentage"] is None
    downloads.run(job["id"])
    result = downloads.get(job["id"])
    assert result["status"] == "complete" and result["total_bytes"] == result["downloaded_bytes"]
    assert result["total_bytes"] > 0
