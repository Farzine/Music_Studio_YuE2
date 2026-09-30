"""File availability, inference prerequisites and selector state stay separate."""
from __future__ import annotations

import json
import asyncio

import pytest

from app.services.capabilities import CapabilityService
from app.services.generations import GenerationService
from yue2_studio_core.errors import ErrorCode, StudioError, ValidationError
from yue2_studio_core.models import GenerationConfig
from yue2_studio_core.parameters import describe_registry
from yue2_studio_core.settings import Settings


@pytest.fixture()
def installed_gguf(tmp_path):
    model = tmp_path / "models" / "gguf"
    model.mkdir(parents=True)
    filename = "yue2-3b-q4_0.gguf"
    (model / "studio-model.json").write_text(json.dumps({
        "repo_id": "audio-cpp/Yue2-3B-GGUF", "revision": "a" * 40, "filename": filename,
    }))
    for name in (
        filename, "yue2-vae-f16.gguf", "sidecars/yue2-model-config.json",
        "sidecars/yue2-generation-config.json", "sidecars/yue2-qwen.tiktoken",
        "sidecars/yue2-vae-config.json",
    ):
        path = model / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"fixture")
        if name.endswith(".json"):
            path.write_text(json.dumps({"model_type": "yue2_vae" if "vae-config" in name else "yue2"}))
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        yue2_model_path=str(model), yue2_models_dir=str(model.parent),
        audiocpp_cli_path=str(tmp_path / "missing-cli"),
    )
    return model, settings


def model_option(service, monkeypatch):
    monkeypatch.setattr(service, "capabilities", lambda backend=None: {
        "label": "test", "modes": ["full", "off"], "capabilities": {},
        "models": service.local_models(),
    })
    parameter = next(p for p in service.schema()["parameters"] if p["key"] == "model.checkpoint")
    return parameter["options"][0]


def test_downloaded_files_remain_downloaded_without_runtime(installed_gguf, monkeypatch):
    model, settings = installed_gguf
    service = CapabilityService(settings)
    entry = service.resolve_model_choice(str(model))
    assert entry["download_status"] == "downloaded"
    assert entry["files_complete"] is True
    assert entry["validation_status"] == "not_validated"
    assert entry["currently_loaded"] is None
    assert entry["parameter_count"] is None
    assert entry["inference_status"] == "runtime_unavailable"
    assert entry["inference_ready"] is False
    assert "audio.cpp CLI" in entry["problem"]
    assert service.resolve_model_choice("default") == entry
    option = model_option(service, monkeypatch)
    assert option["enabled"] is False
    assert option["disabled_reason"] == entry["problem"]


def test_runtime_change_does_not_change_file_or_validation_state(installed_gguf):
    model, settings = installed_gguf
    service = CapabilityService(settings)
    before = service.resolve_model_choice("default")
    cli = model.parent / "audiocpp_cli"
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    settings.audiocpp_cli_path = str(cli)
    after = service.resolve_model_choice("default")
    assert after["inference_ready"] is True
    assert after["inference_status"] == "ready"
    assert after["problem"] is None
    for key in ("download_status", "files_complete", "validation_status", "currently_loaded"):
        assert before[key] == after[key]


def test_missing_sidecars_are_not_reported_as_missing_main_weights(installed_gguf):
    model, settings = installed_gguf
    (model / "sidecars/yue2-vae-config.json").unlink()
    entry = CapabilityService(settings).resolve_model_choice("default")
    assert entry["download_status"] == "downloaded"
    assert entry["files_complete"] is False
    assert entry["inference_status"] == "files_missing"
    assert "sidecars/yue2-vae-config.json" in entry["problem"]


def test_schema_keeps_disabled_dynamic_options_and_their_reason(data_dir):
    capabilities = {"label": "test", "modes": ["full"], "capabilities": {}}
    schema = describe_registry(capabilities, {"models": [
        {"value": "missing", "label": "Missing", "enabled": False, "disabled_reason": "Install runtime"},
        {"value": "ready", "label": "Ready", "enabled": True},
    ]})
    options = next(p for p in schema["parameters"] if p["key"] == "model.checkpoint")["options"]
    assert options[0]["enabled"] is False
    assert options[0]["disabled_reason"] == "Install runtime"
    assert options[1]["enabled"] is True


def test_api_reports_missing_runtime_as_capability_not_missing_weights(installed_gguf):
    model, settings = installed_gguf
    service = GenerationService(
        store=None, queue=None, budget=None, settings=settings,
        capabilities=CapabilityService(settings),
    )
    for checkpoint in ("default", str(model)):
        config = GenerationConfig.model_validate({"model": {"checkpoint": checkpoint}})
        with pytest.raises(StudioError) as caught:
            service._validate_model(config)
        assert caught.value.code is ErrorCode.UNSUPPORTED_CAPABILITY
        assert caught.value.details["inference_status"] == "runtime_unavailable"


def test_vae_cannot_be_submitted_as_inference_model(tmp_path):
    vae = tmp_path / "models" / "vae"
    vae.mkdir(parents=True)
    (vae / "config.json").write_text('{"model_type":"yue2_vae"}')
    (vae / "model.safetensors").write_bytes(b"fixture")
    settings = Settings(data_dir=str(tmp_path / "data"), yue2_models_dir=str(vae.parent))
    service = GenerationService(
        store=None, queue=None, budget=None, settings=settings,
        capabilities=CapabilityService(settings),
    )
    with pytest.raises(ValidationError, match="VAE"):
        service._validate_model(GenerationConfig.model_validate({"model": {"checkpoint": str(vae)}}))


def test_default_gguf_dispatches_to_audiocpp_without_rewriting_request(installed_gguf, data_dir, monkeypatch):
    from services.yue2_worker import worker as worker_module
    from yue2_studio_core.ids import new_id
    from yue2_studio_core.models import GenerationJob, JobStatus
    from yue2_studio_core.settings import get_settings

    model, _ = installed_gguf
    monkeypatch.setenv("YUE2_MODEL_PATH", str(model))
    get_settings.cache_clear()
    chosen = []

    class SelectedBackend:
        def __init__(self, settings, store, device):
            chosen.append(settings.model_reference)

        async def validate_config(self, config):
            assert config.model.checkpoint == "default"
            raise StudioError(ErrorCode.CANCELLED, "Dispatch checked without GPU inference")

        async def shutdown(self):
            pass

    monkeypatch.setattr(worker_module, "AudioCppBackend", SelectedBackend)
    monkeypatch.setattr(worker_module, "reset_gpu_peak", lambda index: None)
    worker = worker_module.Worker(once=True)
    project = worker.store.create_project(title="dispatch")
    job = GenerationJob(id=new_id("gen"), project_id=project.id, config=GenerationConfig())
    worker.store.save_job(job)
    asyncio.run(worker.run_job(job))
    assert chosen == [str(model)]
    stored = worker.store.get_job(job.id)
    assert stored.status is JobStatus.CANCELLED
    assert stored.config.model.checkpoint == "default"


@pytest.mark.parametrize("metadata", [
    "[]", '{"filename":"../outside.gguf"}', "not json",
    '{"filename":"yue2-3b-q4_0.gguf","repo_id":123}',
])
def test_invalid_installation_metadata_is_an_explicit_failure(installed_gguf, metadata):
    model, settings = installed_gguf
    (model / "studio-model.json").write_text(metadata)
    entry = CapabilityService(settings).resolve_model_choice("default")
    assert entry["inference_ready"] is False
    assert entry["inference_status"] == "validation_failed"
    assert entry["validation_status"] == "failed"
    assert entry["download_status"] == "unknown"
    assert entry["problem"]
    service = GenerationService(
        store=None, queue=None, budget=None, settings=settings,
        capabilities=CapabilityService(settings),
    )
    with pytest.raises(StudioError) as caught:
        service._validate_model(GenerationConfig())
    assert caught.value.code is ErrorCode.INVALID_CONFIG


def test_unsupported_gguf_architecture_is_downloaded_but_incompatible(installed_gguf):
    model, settings = installed_gguf
    (model / "yue2-3b-q4_0.gguf").rename(model / "other-model.gguf")
    (model / "studio-model.json").write_text('{"filename":"other-model.gguf"}')
    (model / "sidecars/yue2-model-config.json").write_text('{"model_type":"llama"}')
    entry = CapabilityService(settings).resolve_model_choice("default")
    assert entry["download_status"] == "downloaded"
    assert entry["files_complete"] is True
    assert entry["compatibility_status"] == "incompatible"
    assert entry["inference_status"] == "incompatible"
    assert not entry["inference_ready"]
