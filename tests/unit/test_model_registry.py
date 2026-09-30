"""Registry migration and recovery use temporary files, without weights or CUDA."""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.services.capabilities import CapabilityService
from yue2_studio_core.errors import ValidationError
from yue2_studio_core.model_metadata import GGUF_COMPANIONS
from yue2_studio_core.model_registry import ModelRegistry
from yue2_studio_core.settings import Settings


def native(path: Path, kind: str = "yue2") -> Path:
    path.mkdir(parents=True)
    (path / "config.json").write_text(json.dumps({"model_type": kind}))
    (path / "model.safetensors").write_bytes(b"test weights")
    return path


def gguf(path: Path, revision: str = "a" * 40) -> Path:
    path.mkdir(parents=True)
    filename = "yue2-3b-q4_0.gguf"
    for name in (filename, *GGUF_COMPANIONS):
        target = path / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b"test weights")
        if name.endswith(".json"):
            target.write_text(json.dumps({"model_type": "yue2_vae" if "vae-config" in name else "yue2"}))
    (path / "studio-model.json").write_text(json.dumps({
        "repo_id": "audio-cpp/Yue2-3B-GGUF", "revision": revision, "filename": filename,
    }))
    return path


@pytest.fixture()
def registry(tmp_path):
    root = tmp_path / "models"
    settings = Settings(data_dir=str(tmp_path / "data"), yue2_models_dir=str(root),
                        yue2_model_path=str(root / "native"), yue2_vae_path=str(root / "vae"),
                        yue2_vae_legacy_path=str(root / "legacy"), audiocpp_cli_path=str(tmp_path / "missing-cli"))
    return ModelRegistry(settings)


def test_import_is_durable_idempotent_and_keeps_legacy_references(registry):
    root = registry.settings.models_path
    model = native(root / "native")
    vae = native(root / "vae", "yue2_vae")
    legacy = native(root / "legacy", "yue2_vae")
    variant = gguf(root / "hub" / "variant-3B")
    originals = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    entries = registry.inventory()
    assert {item.id for item in entries} == {str(path) for path in (model, vae, legacy, variant)}
    assert all(item.registration_status == "registered" for item in entries)
    assert len({item.registry_id for item in entries}) == 4
    assert next(item for item in entries if item.id == str(variant)).parameter_count is None
    snapshot, mtime = registry.path.read_bytes(), registry.path.stat().st_mtime_ns
    fresh = ModelRegistry(registry.settings)
    assert fresh.inventory() == entries
    assert registry.path.read_bytes() == snapshot
    assert registry.path.stat().st_mtime_ns == mtime
    assert all(path.read_bytes() == contents for path, contents in originals.items())
    service = CapabilityService(registry.settings)
    assert service.resolve_model_choice("default")["id"] == str(model)
    assert {item["role"] for item in service.local_models()} == {"model", "vae"}
    record = next(item for item in json.loads(snapshot)["entries"] if item["reference"] == str(variant))
    assert record["revision"] == record["commit_hash"] == "a" * 40
    assert not {"inference_status", "currently_loaded", "is_default", "download_status"} & record.keys()


def test_aliases_deduplicate_and_resolve_without_rewriting_configuration(registry):
    root = registry.settings.models_path
    model = native(root / "native")
    alias = root / "alias"
    alias.symlink_to(model, target_is_directory=True)
    registry.settings.yue2_model_path = str(alias)
    entries = [item for item in registry.inventory() if item.registry_id]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == str(alias) and entry.is_default
    assert entry.aliases == sorted([str(model), str(alias)])
    service = CapabilityService(registry.settings)
    assert service.resolve_model_choice(str(model))["registry_id"] == entry.registry_id
    assert service.resolve_model_choice(str(alias))["registry_id"] == entry.registry_id
    registry.settings.yue2_model_path = str(model)
    assert service.resolve_model_choice("default")["registry_id"] == entry.registry_id
    alias.unlink()
    assert service.resolve_model_choice(str(alias)) is None
    # A retargeted alias must resolve to its new installation, not the old record.
    replacement = native(root / "replacement")
    alias.symlink_to(replacement, target_is_directory=True)
    assert service.resolve_model_choice(str(alias))["registry_id"] != entry.registry_id


def test_removed_installation_retains_identity_and_provenance_but_loses_readiness(registry):
    model = gguf(registry.settings.models_path / "hub" / "variant")
    before = registry.register(str(model))
    shutil.rmtree(model)
    after = next(item for item in registry.inventory() if item.registry_id == before.registry_id)
    assert after.registration_status == "registered"
    assert after.download_status == "missing" and not after.inference_ready
    assert after.huggingface_repo == before.huggingface_repo
    assert after.bytes == before.bytes and after.created_at == before.created_at
    assert after.updated_at == before.updated_at
    gguf(model)
    restored = next(item for item in registry.inventory() if item.registry_id == before.registry_id)
    assert restored.download_status == "downloaded" and restored.inference_ready


def test_missing_gguf_metadata_never_turns_registered_weights_into_native_model(registry):
    model = gguf(registry.settings.models_path / "hub" / "variant")
    before = registry.register(str(model))
    (model / "studio-model.json").unlink()
    after = next(item for item in registry.inventory() if item.registry_id == before.registry_id)
    assert after.download_status == "downloaded"
    assert after.format == "gguf" and not after.inference_ready
    assert after.inference_status == "files_missing"
    assert "studio-model.json" in after.problem


def test_metadata_changes_update_existing_record_without_guessing_counts(registry):
    model = gguf(registry.settings.models_path / "hub" / "variant", revision="main")
    before = registry.register(str(model))
    assert before.commit_hash is None and before.parameter_count is None
    metadata = json.loads((model / "studio-model.json").read_text())
    metadata["revision"] = "b" * 40
    (model / "studio-model.json").write_text(json.dumps(metadata))
    after = registry.register(str(model))
    assert before.registry_id == after.registry_id
    assert before.created_at == after.created_at and before.updated_at < after.updated_at
    assert after.commit_hash == "b" * 40
    assert after.parameter_count is None
    metadata["revision"] = "main"
    (model / "studio-model.json").write_text(json.dumps(metadata))
    assert registry.register(str(model)).commit_hash is None


@pytest.mark.parametrize("damage", ["truncated", "newer_version", "duplicate", "unsafe_filename"])
def test_registry_errors_preserve_original_and_recover_from_backup(registry, damage):
    native(registry.settings.models_path / "native")
    before = registry.inventory()
    backup = registry.path.read_bytes()
    document = json.loads(backup)
    if damage == "truncated":
        broken = b'{"entries":'
    else:
        if damage == "newer_version":
            document["schema_version"] = 2
        elif damage == "duplicate":
            document["entries"].append(document["entries"][0])
        else:
            document["entries"][0]["filename"] = "../outside.safetensors"
        broken = json.dumps(document).encode()
    registry.path.write_bytes(broken)
    with pytest.raises(ValidationError, match="left unchanged"):
        registry.inventory()
    assert registry.path.read_bytes() == broken
    registry.path.write_bytes(backup)
    assert registry.inventory() == before
    # An explicit rebuild recovers the deterministic IDs without touching weights.
    registry.path.rename(registry.path.with_suffix(".damaged"))
    rebuilt = registry.inventory()
    assert [item.registry_id for item in rebuilt] == [item.registry_id for item in before]


def test_concurrent_registrations_do_not_lose_entries_and_external_paths_stay_visible(registry, tmp_path):
    paths = [native(tmp_path / "external" / f"model-{index}") for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = list(pool.map(lambda path: ModelRegistry(registry.settings).register(str(path)), paths))
    installed = [item for item in registry.inventory() if item.registry_id]
    assert {item.registry_id for item in installed} == {item.registry_id for item in entries}
    assert len(json.loads(registry.path.read_text())["entries"]) == len(paths)


def test_remote_defaults_and_unrecognized_directories_are_not_registered(registry):
    root = registry.settings.models_path
    root.mkdir()
    (root / "partial").mkdir()
    (root / "partial" / "model.safetensors.part").write_bytes(b"partial")
    (root / "unrelated").mkdir()
    (root / "unrelated" / "config.json").write_text("[]")
    entries = registry.inventory()
    assert len(entries) == 3
    assert all(item.registration_status == "discovered" and not item.registry_id for item in entries)
    assert not registry.path.exists()
