"""Structural validation, file leases and confirmed deletion, without a GPU."""
import hashlib
import json
import os
import struct
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.models import ModelService
from yue2_studio_core.errors import ConflictError, NotFoundError
from yue2_studio_core.ids import new_id
from yue2_studio_core.model_files import model_file_leases
from yue2_studio_core.model_metadata import GGUF_COMPANIONS, describe_model_files
from yue2_studio_core.model_registry import ModelRegistry
from yue2_studio_core.model_validator import gguf_metadata, safetensors_metadata, validate_installation
from yue2_studio_core.models import GenerationConfig, GenerationJob, JobStatus
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import file_lock


def gguf(path: Path, *, architecture="audiocpp", family="yue2", kind=2):
    def string(value):
        value = value.encode()
        return struct.pack("<Q", len(value)) + value
    metadata = [("general.architecture", architecture)]
    if family:
        metadata.append(("audiocpp.model_spec.family", family))
    header = b"GGUF" + struct.pack("<IQQ", 3, 1, len(metadata))
    for key, value in metadata:
        header += string(key) + struct.pack("<I", 8) + string(value)
    shape = 32 if kind == 2 else 2
    header += string("weight") + struct.pack("<IQIQ", 1, shape, kind, 0)
    header += b"\0" * (-len(header) % 32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + b"\0" * (18 if kind == 2 else 4))


@pytest.fixture()
def installed(tmp_path, native_model_files):
    root = tmp_path / "models"
    model = native_model_files(root / "native")
    settings = Settings(data_dir=str(tmp_path / "data"), yue2_models_dir=str(root),
                        yue2_model_path=str(model), yue2_vae_path=str(root / "vae"),
                        yue2_vae_legacy_path=str(root / "legacy"))
    registry = ModelRegistry(settings)
    record = registry.register(str(model))
    return ModelService(registry), model, record.registry_id


def test_structural_validation_reports_real_elements_not_invented_parameters(installed):
    service, model, registry_id = installed
    report = service.validate(registry_id)["validation"]
    assert report["validation_status"] == "validated" and not report["checksum_verified"]
    assert report["facts"]["precision"] == "F16"
    assert report["facts"]["tensor_element_count"] == 2
    assert report["facts"]["parameter_count"] is None
    entry = next(item for item in service.registry.inventory() if item.registry_id == registry_id)
    assert entry.validation_status == "validated" and entry.inference_ready
    snapshot = service.registry.path.read_bytes()
    service.registry.inventory()
    assert snapshot == service.registry.path.read_bytes()


def test_changed_config_keeps_specific_corruption_error(installed):
    service, model, registry_id = installed
    service.validate(registry_id)
    (model / "config.json").write_text("broken json")
    entry = next(item for item in service.registry.inventory() if item.registry_id == registry_id)
    assert entry.validation_status == "failed" and entry.inference_status == "validation_failed"


@pytest.mark.parametrize("damage", [b"text", struct.pack("<Q", 2**64-1),
    struct.pack("<Q", 56) + b'{"a":{"dtype":"F16","shape":[2],"data_offsets":[0,8]}}'])
def test_corrupt_native_weights_fail_and_disable_inventory(installed, damage):
    service, model, registry_id = installed
    (model / "model.safetensors").write_bytes(damage)
    report = service.validate(registry_id)["validation"]
    assert report["validation_status"] == "failed"
    entry = next(item for item in service.registry.inventory() if item.registry_id == registry_id)
    assert entry.inference_status == "validation_failed" and not entry.inference_ready


def test_safetensors_duplicate_keys_and_unindexed_data_are_rejected(tmp_path):
    path = tmp_path / "weights.safetensors"
    tensor = '{"dtype":"F16","shape":[1],"data_offsets":[0,2]}'
    for header, payload in [(f'{{"a":{tensor},"a":{tensor}}}', b"\0\0"), (f'{{"a":{tensor}}}', b"\0\0extra")]:
        data = header.encode()
        path.write_bytes(struct.pack("<Q", len(data)) + data + payload)
        with pytest.raises(ValueError):
            safetensors_metadata(path)


def test_checksum_verification_and_changed_file_invalidation(installed):
    service, model, registry_id = installed
    weights = model / "model.safetensors"
    wanted = hashlib.sha256(weights.read_bytes()).hexdigest()
    (model / "weights_manifest.json").write_text(json.dumps({"files": {weights.name: {"sha256": wanted, "bytes": weights.stat().st_size}}}))
    report = service.validate(registry_id, verify_checksum=True)["validation"]
    assert report["validation_status"] == "validated" and report["checksum_verified"]
    assert report["facts"]["checksum_sha256"] == wanted
    weights.write_bytes(weights.read_bytes()[:-1] + b"\1")
    entry = next(item for item in service.registry.inventory() if item.registry_id == registry_id)
    assert entry.validation_status == "not_validated" and not entry.inference_ready
    assert entry.checksum_sha256 is None
    assert entry.precision is None and entry.tensor_element_count is None
    report = service.validate(registry_id, verify_checksum=True)["validation"]
    assert report["validation_status"] == "failed" and "Checksum mismatch" in report["problem"]


def test_computed_hash_without_expected_hash_is_not_checksum_verified(installed):
    service, _, registry_id = installed
    report = service.validate(registry_id, verify_checksum=True)["validation"]
    assert report["checksums"] and not report["checksum_verified"]


def test_real_audiocpp_gguf_layout_is_validated_without_filename_assumptions(tmp_path):
    root = tmp_path / "models" / "variant"
    filename = "custom.gguf"
    gguf(root / filename)
    gguf(root / "yue2-vae-f16.gguf", family=None, kind=1)
    for name in GGUF_COMPANIONS:
        path = root / name
        if name.endswith(".json"):
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({"model_type": "yue2_vae" if "vae-config" in name else "yue2"}))
        elif name.endswith(".tiktoken"):
            path.write_bytes(b"tokenizer")
    (root / "studio-model.json").write_text(json.dumps({"filename": filename}))
    entry = describe_model_files(str(root), "model")
    report = validate_installation(entry.model_copy(update={"registry_id": "test"}))
    assert report.validation_status == "validated" and report.compatibility_status == "supported"
    assert report.facts["quantization"] == "Q4_0" and report.facts["architecture"] == "audiocpp"
    assert report.facts["parameter_count"] is None
    gguf(root / filename, family="another_family")
    report = validate_installation(entry.model_copy(update={"registry_id": "test"}))
    assert report.compatibility_status == "incompatible"
    gguf(root / filename)
    (root / filename).write_bytes((root / filename).read_bytes()[:-1])
    with pytest.raises(ValueError, match="beyond"):
        gguf_metadata(root / filename)


def test_unknown_gguf_version_is_never_claimed_validated(tmp_path):
    path = tmp_path / "model.gguf"
    gguf(path)
    data = path.read_bytes()
    path.write_bytes(data[:4] + struct.pack("<I", 99) + data[8:])
    with pytest.raises(ValueError, match="different structural reader"):
        gguf_metadata(path)


def confirm(service, registry_id):
    preview = service.preview(registry_id)
    return service.delete(registry_id, confirmation_token=preview["confirmation_token"], confirmed_path=preview["path"])


def test_confirmed_delete_preserves_shared_files_and_cleans_partial_files(installed, tmp_path):
    service, model, registry_id = installed
    outside = tmp_path / "shared.gguf"
    outside.write_bytes(b"shared")
    (model / "linked.gguf").symlink_to(outside)
    os.link(outside, model / "hardlinked.gguf")
    (model / "download.part").write_bytes(b"partial")
    service.validate(registry_id)
    preview = service.preview(registry_id)
    assert preview["can_delete"] and any(item["path"] == "download.part" for item in preview["files"])
    assert confirm(service, registry_id)["complete"]
    assert not model.exists() and outside.read_bytes() == b"shared"
    assert not any(item.registry_id == registry_id for item in service.registry.inventory())
    with pytest.raises(NotFoundError):
        service.registry.get(registry_id)


def test_confirmation_rejects_changed_directory(installed):
    service, model, registry_id = installed
    preview = service.preview(registry_id)
    (model / "new-file").write_bytes(b"new data")
    with pytest.raises(ConflictError, match="changed"):
        service.delete(registry_id, confirmation_token=preview["confirmation_token"], confirmed_path=preview["path"])
    assert model.exists()


@pytest.mark.parametrize("status", [JobStatus.QUEUED, JobStatus.GENERATING, JobStatus.CANCEL_REQUESTED])
@pytest.mark.parametrize("reference", ["default", "explicit", "vae"])
def test_active_model_and_vae_references_block_deletion(installed, status, reference):
    service, model, registry_id = installed
    fields = {"checkpoint": str(model) if reference == "explicit" else "default"}
    if reference == "vae":
        fields = {"checkpoint": "another", "vae": str(model)}
    job = GenerationJob(id=new_id("gen"), project_id=new_id("prj"), config=GenerationConfig(model=fields), status=status)
    service.store.save_job(job)
    preview = service.preview(registry_id)
    assert not preview["can_delete"]
    with pytest.raises(ConflictError, match="Task"):
        confirm(service, registry_id)
    assert model.exists()


def test_file_lease_refuses_delete_during_runtime_or_transfer(installed):
    service, model, registry_id = installed
    with model_file_leases(service.store, [str(model)]):
        assert not service.preview(registry_id)["can_delete"]
        with pytest.raises(ConflictError, match="in use"):
            confirm(service, registry_id)
    assert confirm(service, registry_id)["complete"]


def test_cleanup_failure_keeps_journal_and_can_be_retried_without_reimport(installed, monkeypatch):
    service, model, registry_id = installed
    with monkeypatch.context() as scoped:
        scoped.setattr("app.services.models.shutil.rmtree", lambda path: (_ for _ in ()).throw(OSError("permission denied")))
        result = confirm(service, registry_id)
    assert not result["deleted"] and not result["complete"]
    assert not model.exists()
    entries = [item for item in service.registry.inventory() if item.registry_id]
    assert len(entries) == 1 and entries[0].deletion_status == "deleting" and not entries[0].inference_ready
    assert confirm(service, registry_id)["complete"]


def test_external_and_nested_installations_cannot_be_deleted(installed, tmp_path, native_model_files):
    service, model, registry_id = installed
    external = native_model_files(tmp_path / "external")
    record = service.registry.register(str(external))
    assert not service.preview(record.registry_id)["can_delete"]
    with pytest.raises(ConflictError, match="outside"):
        confirm(service, record.registry_id)
    service.registry.register(str(native_model_files(model / "nested")))
    with pytest.raises(ConflictError, match="overlaps"):
        confirm(service, registry_id)


def test_unreadable_task_records_fail_closed(installed):
    service, model, registry_id = installed
    (service.store.jobs_dir / "gen_broken.json").write_text("broken")
    with pytest.raises(ConflictError, match="unreadable"):
        confirm(service, registry_id)
    assert model.exists()


def test_older_live_worker_heartbeat_protects_idle_residency(installed):
    service, model, registry_id = installed
    root = service.store.root / "worker"
    root.mkdir()
    (root / "old-worker.json").write_text(json.dumps({"pid": os.getpid(), "model": {"loaded": True, "model": str(model)}}))
    with pytest.raises(ConflictError, match="loaded"):
        confirm(service, registry_id)


def test_model_manager_releases_leases_on_unload_and_failed_load(installed, monkeypatch, native_model_files):
    from services.yue2_worker.model_manager.manager import ModelManager
    service, model, registry_id = installed
    native_model_files(service.settings.models_path / "vae", role="vae")
    manager = ModelManager(service.settings, service.store)
    def load(config, key):
        manager._key = key
        manager._pipeline = SimpleNamespace(close=lambda: None)
        return manager._pipeline, True
    monkeypatch.setattr(manager, "_load", load)
    monkeypatch.setattr(manager, "_check_runtime", lambda config, key: None)
    monkeypatch.setitem(__import__("sys").modules, "torch", SimpleNamespace(cuda=SimpleNamespace(
        device=lambda index: nullcontext(), synchronize=lambda index: None, empty_cache=lambda: None,
        ipc_collect=lambda: None, memory_allocated=lambda index: 0, memory_reserved=lambda index: 0)))
    manager.acquire(GenerationConfig())
    assert not service.preview(registry_id)["can_delete"]
    manager.release()
    assert service.preview(registry_id)["can_delete"]
    def fail(config, key):
        raise ValueError("load failed")
    monkeypatch.setattr(manager, "_load", fail)
    with pytest.raises(ValueError, match="load failed"):
        manager.acquire(GenerationConfig())
    assert service.preview(registry_id)["can_delete"]


def test_model_manager_checks_architecture_through_shared_descriptor(installed):
    from services.yue2_worker.model_manager.manager import ModelManager
    from yue2_studio_core.errors import ErrorCode, StudioError
    service, model, _ = installed
    (model / "config.json").write_text('{"model_type":"llama"}')
    with pytest.raises(StudioError) as caught:
        ModelManager(service.settings, service.store).verify_files(GenerationConfig())
    assert caught.value.code is ErrorCode.UNSUPPORTED_CAPABILITY


def test_admission_is_serialized_with_deletion(installed, monkeypatch):
    from app.services.generations import GenerationService
    from yue2_studio_core.queue import FilesystemJobQueue
    service, model, registry_id = installed
    budget = SimpleNamespace(estimate=lambda config: SimpleNamespace(to_dict=lambda: {}))
    generations = GenerationService(store=service.store, queue=FilesystemJobQueue(service.store),
                                    capabilities=None, budget=budget, settings=service.settings)
    started, proceed = threading.Event(), threading.Event()
    def validate(config):
        started.set()
        assert proceed.wait(10)
        return []
    monkeypatch.setattr(generations, "validate_config", validate)
    preview = service.preview(registry_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = pool.submit(generations.create_generation, overrides={"prompt": {"style": "music", "lyrics": "lyrics"}})
        assert started.wait(10)
        try:
            with pytest.raises(ConflictError):
                with file_lock(service.store.jobs_dir / ".queue.lock", blocking=False):
                    pass
            removal = pool.submit(service.delete, registry_id, confirmation_token=preview["confirmation_token"], confirmed_path=preview["path"])
        finally:
            proceed.set()
        assert admitted.result(timeout=10)[0].status is JobStatus.QUEUED
        with pytest.raises(ConflictError, match="Task"):
            removal.result(timeout=10)
    assert model.is_dir()
