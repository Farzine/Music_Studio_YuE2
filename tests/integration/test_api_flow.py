"""API surface: schema, validation, job creation, queue and artifacts."""
from __future__ import annotations

import json


def test_health_and_schema_are_served(api_client):
    health = api_client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["backend"] == "mock"

    schema = api_client.get("/api/v1/generation/schema")
    assert schema.status_code == 200
    body = schema.json()
    assert len(body["parameters"]) > 30
    # The frontend renders from this; unsupported settings arrive disabled.
    disabled = [p for p in body["parameters"] if not p["enabled"]]
    assert disabled and all(p.get("disabled_reason") for p in disabled)


def test_capabilities_report_reasons_for_everything_unavailable(api_client):
    body = api_client.get("/api/v1/models/capabilities").json()
    for name, entry in body["capabilities"].items():
        if not entry["supported"]:
            assert entry.get("reason"), f"{name} is off with no reason"


def test_creating_a_generation_queues_it(api_client, sample_config):
    response = api_client.post("/api/v1/generations", json={"title": "Test", "config": sample_config})
    assert response.status_code == 201
    body = response.json()
    job = body["generation"]
    assert job["status"] == "QUEUED"
    assert job["config"]["sampling"]["seed"] == 4242
    assert job["config"]["sampling"]["max_tokens"] == 500  # 20s at 25 frames per second

    queue = api_client.get("/api/v1/queue").json()
    assert queue["depth"] == 1
    assert queue["max_concurrent_gpu_jobs"] == 1


def test_randomised_seed_is_resolved_server_side_and_reported(api_client, sample_config):
    config = json.loads(json.dumps(sample_config))
    config["sampling"]["control_after_generate"] = "randomize"
    job = api_client.post("/api/v1/generations", json={"config": config}).json()["generation"]
    assert job["config"]["sampling"]["seed"] != 4242
    # The stored behaviour is fixed, so re-running reproduces this exact take.
    assert job["config"]["sampling"]["control_after_generate"] == "fixed"


def test_missing_style_is_rejected_by_the_server(api_client):
    response = api_client.post(
        "/api/v1/generations", json={"config": {"prompt": {"style": "", "lyrics": "x"}}}
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_CONFIG"


def test_comfy_only_parameters_are_refused_with_an_explanation(api_client, sample_config):
    config = json.loads(json.dumps(sample_config))
    config["synthesis"] = {"sampler_name": "dpm_2"}
    response = api_client.post("/api/v1/generations", json={"config": config})
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "UNSUPPORTED_CAPABILITY"
    assert "sampler_name" in json.dumps(body["details"])


def test_unavailable_mode_is_refused(api_client, sample_config):
    config = json.loads(json.dumps(sample_config))
    config["prompt"]["mode"] = "cover"
    config["prompt"]["abc"] = "X:1\n"
    response = api_client.post("/api/v1/generations", json={"config": config})
    assert response.status_code in {409, 422}


def test_invalid_abc_is_refused(api_client, sample_config):
    config = json.loads(json.dumps(sample_config))
    config["prompt"]["mode"] = "score_edit"
    config["prompt"]["abc"] = "definitely not a score"
    response = api_client.post("/api/v1/generations", json={"config": config})
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_ABC"


def test_cancel_retry_and_duplicate(api_client, sample_config):
    job = api_client.post("/api/v1/generations", json={"config": sample_config}).json()["generation"]

    cancelled = api_client.post(f"/api/v1/generations/{job['id']}/cancel").json()
    assert cancelled["status"] == "CANCELLED"

    retried = api_client.post(f"/api/v1/generations/{job['id']}/retry")
    assert retried.status_code == 201
    assert retried.json()["config"]["sampling"]["seed"] == 4242

    duplicated = api_client.post(
        f"/api/v1/generations/{job['id']}/duplicate",
        json={"sampling": {"seed": 777}},
    )
    assert duplicated.status_code == 201
    assert duplicated.json()["config"]["sampling"]["seed"] == 777


def test_presets_expose_defaults_and_accept_new_ones(api_client):
    body = api_client.get("/api/v1/presets").json()
    names = {preset["name"] for preset in body["items"]}
    assert {"Balanced", "High Quality", "Fast Preview"} <= names
    assert body["defaults"]["synthesis"]["ode_steps"] == 32

    created = api_client.post(
        "/api/v1/presets", json={"name": "Mine", "config": {"synthesis": {"ode_steps": 48}}}
    )
    assert created.status_code == 201
    assert created.json()["config"]["synthesis"]["ode_steps"] == 48

    assert {p["name"] for p in api_client.get("/api/v1/presets").json()["items"]} >= {"Mine"}


def test_builtin_presets_cannot_be_deleted(api_client):
    assert api_client.delete("/api/v1/presets/preset_balanced").status_code == 409


def test_artifact_paths_cannot_escape_the_data_directory(api_client, sample_config):
    job = api_client.post("/api/v1/generations", json={"config": sample_config}).json()["generation"]
    response = api_client.get(
        f"/api/v1/artifacts/{job['id']}/file", params={"path": "../../../etc/passwd"}
    )
    assert response.status_code == 404


def test_unknown_generation_returns_a_typed_error(api_client):
    response = api_client.get("/api/v1/generations/gen_doesnotexist0")
    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


def test_upload_rejects_a_non_audio_file(api_client):
    response = api_client.post(
        "/api/v1/uploads", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "AUDIO_INPUT_ERROR"
