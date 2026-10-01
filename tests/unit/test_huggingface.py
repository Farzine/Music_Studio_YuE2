"""Offline repository metadata, safe selection and storage planning."""
from types import SimpleNamespace

import pytest
from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError, RevisionNotFoundError
from requests.exceptions import ConnectionError

from app.services.huggingface import HuggingFaceService, hub_error, validate_source
from yue2_studio_core.errors import NotFoundError, ValidationError
from yue2_studio_core.model_metadata import GGUF_COMPANIONS, ModelMetadata
from yue2_studio_core.model_recommendations import model_memory
from yue2_studio_core.settings import Settings


def service(tmp_path):
    return HuggingFaceService(Settings(data_dir=str(tmp_path / "data"), yue2_models_dir=str(tmp_path / "models")))


@pytest.mark.parametrize("filename", ["../x.gguf", "/x.gguf", "a//x.gguf", "a/./x.gguf", "C:x.gguf", "a\\x.gguf", "x\0.gguf", ""])
def test_rejects_unsafe_file_paths(filename):
    with pytest.raises(ValidationError):
        validate_source("owner/repository", filename)


def test_inspection_pins_commit_and_separates_hints_from_facts(tmp_path, hub_repository):
    result = service(tmp_path).inspect("owner/repository", "v1")
    assert result["revision"] == "a" * 40 and result["requested_revision"] == "v1"
    assert hub_repository.calls[0][1] == {"revision": "v1", "files_metadata": True, "timeout": 20}
    assert {r["kind"] for r in result["revisions"]} == {"branch", "tag"}
    gguf = next(c for c in result["candidates"] if c["model"]["filename"].endswith("q4_0.gguf"))
    assert gguf["quantization_hint"] == "Q4_0"
    assert gguf["model"]["quantization"] is None and gguf["model"]["parameter_count"] is None
    assert not gguf["model"]["inference_ready"] and not gguf["model"]["is_local"]
    native = next(c for c in result["candidates"] if c["model"]["format"] == "safetensors")
    assert native["model"]["parameter_count"] == 1234
    vae = next(c for c in result["candidates"] if c["model"]["role"] == "vae")
    assert vae["model"]["architecture"] == "yue2_vae"
    assert not service(tmp_path).settings.models_path.exists()


def test_remote_config_and_vae_use_the_existing_estimator(tmp_path, hub_repository):
    hub = service(tmp_path)
    result = hub.inspect("owner/repository")
    candidate = result["candidates"][0]["model"]
    memory = model_memory(ModelMetadata.model_validate(candidate), None, hub.settings,
                          **result["candidate_contexts"][candidate["id"]])
    assert memory["kv_source"] == "model_config_full_context_two_cfg_branches"
    assert memory["vae_size_known"] and memory["vae_bytes"] == 128
    assert memory["estimated_peak_bytes"] > candidate["bytes"]


def test_native_decoder_inspection_preserves_role_and_requires_its_configuration(tmp_path, hub_repository):
    hub_repository.configs["config.json"] = {"model_type": "yue2_vae", "latent_dim": 64}
    hub = service(tmp_path)
    inspection = hub.inspect("owner/repository")
    decoder = next(c for c in inspection["candidates"] if c["model"]["filename"] == "model.safetensors")
    assert decoder["model"]["role"] == "vae"
    assert decoder["model"]["parameter_count"] is None
    assert decoder["required_files"] == ["model.safetensors", "config.json"]
    preview = hub.preview(inspection, "model.safetensors", mode="selected", selected_files=[])
    assert preview["missing_required_files"] == ["config.json"]
    with pytest.raises(ValidationError, match="bundled F16"):
        hub.preview(inspection, GGUF_COMPANIONS[0])


def test_preview_modes_and_actual_destination_volume(tmp_path, hub_repository, monkeypatch):
    hub = service(tmp_path)
    result = hub.inspect("owner/repository")
    storage_paths = []
    monkeypatch.setattr("app.services.huggingface.shutil.disk_usage", lambda path: (
        storage_paths.append(path) or SimpleNamespace(free=10 * 2**30)))
    single = hub.preview(result, "custom-3b-q4_0.gguf")
    assert {f["name"] for f in single["files"]} == {"custom-3b-q4_0.gguf", *GGUF_COMPANIONS}
    assert single["total_bytes"] == 128 * 6
    assert single["disk_status"] == "sufficient" and single["can_download"]
    assert storage_paths == [tmp_path]  # missing MODELS_DIR; no write during preview
    selected = hub.preview(result, "model.safetensors", mode="selected", selected_files=["README.md", "README.md"])
    assert len(selected["files"]) == 2 and selected["missing_required_files"] == ["config.json"]
    complete = hub.preview(result, "custom-3b-q4_0.gguf", mode="repository")
    assert len(complete["files"]) == len(result["files"]) and not complete["missing_required_files"]
    assert complete["revision"] == single["revision"]
    with pytest.raises(NotFoundError):
        hub.preview(result, "absent.gguf")
    with pytest.raises(ValidationError):
        hub.preview(result, "model.safetensors", mode="selected", selected_files=["../config.json"])


def test_unknown_sizes_and_insufficient_disk_are_distinct(tmp_path, hub_repository, monkeypatch):
    hub = service(tmp_path)
    hub_repository.info.siblings[0].size = None
    result = hub.inspect("owner/repository")
    monkeypatch.setattr("app.services.huggingface.shutil.disk_usage", lambda path: SimpleNamespace(free=10 * 2**30))
    preview = hub.preview(result, "custom-3b-q4_0.gguf")
    assert preview["total_bytes"] is None and preview["disk_status"] == "unknown"
    monkeypatch.setattr("app.services.huggingface.shutil.disk_usage", lambda path: SimpleNamespace(free=100))
    preview = hub.preview(result, "custom-3b-q4_0.gguf")
    assert preview["disk_status"] == "insufficient" and not preview["can_download"]


def test_missing_files_and_other_architectures_do_not_gain_compatibility(tmp_path, hub_repository):
    hub_repository.configs["config.json"]["model_type"] = "llama"
    hub_repository.info.siblings = [f for f in hub_repository.info.siblings if f.rfilename != GGUF_COMPANIONS[0]]
    result = service(tmp_path).inspect("owner/repository")
    for candidate in result["candidates"]:
        assert candidate["model"]["compatibility_status"] == "incompatible"
    assert any(GGUF_COMPANIONS[0] in c["missing_files"] for c in result["candidates"])


def test_refs_failure_preserves_commit_inspection(tmp_path, hub_repository):
    def failed(*args):
        raise ConnectionError("secret upstream URL")
    hub_repository.api.list_repo_refs = failed
    result = service(tmp_path).inspect("owner/repository")
    assert result["revision"] == "a" * 40 and result["revisions"] == [] and result["warnings"]
    assert "secret" not in str(result)


def test_unknown_vae_metadata_is_not_supported(tmp_path, hub_repository):
    hub_repository.configs["sidecars/yue2-vae-config.json"] = {}
    result = service(tmp_path).inspect("owner/repository")
    gguf = next(c for c in result["candidates"] if c["model"]["filename"] == "custom-3b-q4_0.gguf")
    assert gguf["model"]["compatibility_status"] == "unknown" and not gguf["missing_files"]
    assert not gguf["model"]["inference_ready"]


def test_storage_path_file_is_actionable(tmp_path, hub_repository):
    hub = service(tmp_path)
    hub.settings.models_path.write_text("not a directory")
    with pytest.raises(ValidationError, match="configure a directory"):
        hub.preview(hub.inspect("owner/repository"), "custom-3b-q4_0.gguf")


@pytest.mark.parametrize("exc,error", [(RevisionNotFoundError("secret"), NotFoundError),
                                     (RepositoryNotFoundError("secret"), NotFoundError),
                                     (GatedRepoError("secret"), ValidationError),
                                     (ConnectionError("secret"), ValidationError)])
def test_actionable_errors_do_not_echo_upstream_secrets(exc, error):
    result = hub_error(exc, "owner/repository", "v1")
    assert isinstance(result, error) and "secret" not in result.message


def test_discovery_uses_lineage_filter_and_preserves_partial_errors(tmp_path, hub_repository):
    kwargs_seen = []
    def list_models(**kwargs):
        kwargs_seen.append(kwargs)
        return [SimpleNamespace(id="owner/repository"), SimpleNamespace(id="owner/private")]
    hub_repository.api.list_models = list_models
    model_info = hub_repository.api.model_info
    def inspect(repo, **kwargs):
        if repo == "owner/private":
            raise RepositoryNotFoundError("private")
        return model_info(repo, **kwargs)
    hub_repository.api.model_info = inspect
    result = service(tmp_path).discover("m-a-p/YuE2-3B", 2)
    assert kwargs_seen == [{"filter": "base_model:quantized:m-a-p/YuE2-3B", "limit": 2}]
    assert len(result["items"]) == 2 and "error" in result["items"][0]


@pytest.mark.parametrize("revision", ["../main", "bad?rev", "main\0"])
def test_revision_validation(revision):
    with pytest.raises(ValidationError):
        validate_source("owner/repository", revision=revision)


@pytest.mark.parametrize("payload", [b'{"model_type":"yue2","model_type":"llama"}', b'[]', b'\xff'])
def test_json_inspection_rejects_malformed_metadata(tmp_path, monkeypatch, payload):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): return iter([payload])
    monkeypatch.setattr("app.services.huggingface.get_session", lambda: SimpleNamespace(get=lambda *args, **kwargs: Response()))
    monkeypatch.setattr("app.services.huggingface.hf_raise_for_status", lambda r: None)
    with pytest.raises(ValueError):
        service(tmp_path)._json("owner/repository", "a" * 40, "config.json", {"config.json": {"bytes": None}})


def test_json_inspection_is_commit_pinned_bounded_and_closes_stream(tmp_path, monkeypatch):
    calls, closed = [], []
    chunks = [b'{"model_type":"yue2"}']
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): closed.append(True)
        def iter_content(self, size): return iter(chunks)
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr("app.services.huggingface.get_session", lambda: SimpleNamespace(get=get))
    monkeypatch.setattr("app.services.huggingface.hf_raise_for_status", lambda r: None)
    files = {"config.json": {"bytes": None}}
    hub = service(tmp_path)
    assert hub._json("owner/repository", "a" * 40, "config.json", files) == {"model_type": "yue2"}
    assert "a" * 40 in calls[0][0] and calls[0][1]["stream"] and calls[0][1]["timeout"] == 20
    chunks[:] = [b"x" * (2**20 + 1)]
    with pytest.raises(ValueError, match="1 MiB"):
        hub._json("owner/repository", "a" * 40, "config.json", files)
    assert len(closed) == 2
    files["config.json"]["bytes"] = 2**20 + 1
    with pytest.raises(ValueError, match="1 MiB"):
        hub._json("owner/repository", "a" * 40, "config.json", files)
    assert len(calls) == 2  # declared oversize rejected before transfer
