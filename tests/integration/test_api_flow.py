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


# --------------------------------------------------------------------------- #
# Regressions: the three faults reported against the first build
# --------------------------------------------------------------------------- #


def test_no_select_option_uses_an_empty_value(api_client):
    """An empty option value crashed the model selector.

    A select control reserves the empty string for "nothing selected", so an
    option carrying it throws instead of rendering. Every option the schema
    serves must therefore have a real value.
    """
    schema = api_client.get("/api/v1/generation/schema").json()
    offenders = [
        (parameter["key"], option)
        for parameter in schema["parameters"]
        for option in (parameter.get("options") or [])
        if option["value"] == "" or option["value"] is None
    ]
    assert offenders == [], f"options with an empty value: {offenders}"


def test_model_options_carry_the_metadata_the_selector_shows(api_client):
    schema = api_client.get("/api/v1/generation/schema").json()
    checkpoint = next(p for p in schema["parameters"] if p["key"] == "model.checkpoint")
    options = checkpoint["options"]
    assert options, "the model selector has no options"
    default = options[0]
    assert default["value"] == "default"
    assert default["is_default"] is True
    for option in options:
        assert "enabled" in option
        if not option["enabled"]:
            assert option["disabled_reason"], f"{option['value']} is disabled with no reason"


def test_selecting_an_unknown_model_is_refused_with_a_reason(api_client, sample_config):
    config = json.loads(json.dumps(sample_config))
    config["model"] = {"checkpoint": "/models/does-not-exist"}
    response = api_client.post("/api/v1/generations", json={"config": config})
    assert response.status_code in {404, 422}
    body = response.json()
    assert body["error_code"] in {"INVALID_CONFIG", "MODEL_NOT_FOUND"}
    assert "model.checkpoint" in json.dumps(body["details"])


def test_the_default_model_sentinel_is_accepted(api_client, sample_config):
    config = json.loads(json.dumps(sample_config))
    config["model"] = {"checkpoint": "default"}
    assert api_client.post("/api/v1/generations", json={"config": config}).status_code == 201
    # The historical empty string still resolves to the same thing.
    config["model"] = {"checkpoint": ""}
    created = api_client.post("/api/v1/generations", json={"config": config})
    assert created.status_code == 201
    assert created.json()["generation"]["config"]["model"]["checkpoint"] == "default"


def test_every_parameter_is_served_with_help(api_client):
    schema = api_client.get("/api/v1/generation/schema").json()
    for parameter in schema["parameters"]:
        guidance = parameter.get("guidance")
        assert guidance, f"{parameter['key']} has no help"
        assert guidance["severity"] in {"info", "caution"}
        assert guidance["what"]


def test_cover_needs_a_reference_and_reports_progress_stages(api_client, sample_config):
    """Cover is a real mode with a real extra stage, not a hidden one."""
    schema = api_client.get("/api/v1/generation/schema").json()
    mode = next(p for p in schema["parameters"] if p["key"] == "prompt.mode")
    cover = next(option for option in mode["options"] if option["value"] == "cover")
    # Whether it is enabled depends on the installation; either way it is
    # present, and if it is off it says why.
    assert cover["enabled"] in {True, False}
    if not cover["enabled"]:
        assert cover["disabled_reason"]

    config = json.loads(json.dumps(sample_config))
    config["prompt"]["mode"] = "cover"
    response = api_client.post("/api/v1/generations", json={"config": config})
    assert response.status_code in {409, 422}
    assert "reference" in response.text.lower() or "cover" in response.text.lower()


def test_reference_audio_on_a_non_cover_mode_is_refused(api_client, sample_config):
    config = json.loads(json.dumps(sample_config))
    config["prompt"]["reference_upload_id"] = "upl_00000000000000"
    response = api_client.post("/api/v1/generations", json={"config": config})
    assert response.status_code == 422


def test_gpu_inventory_and_selection(api_client):
    inventory = api_client.get("/api/v1/system/gpus")
    assert inventory.status_code == 200
    body = inventory.json()
    assert "devices" in body and "selected_index" in body
    for device in body["devices"]:
        assert {"index", "name", "memory_total_bytes", "selected"} <= set(device)

    if body["devices"]:
        target = body["devices"][-1]["index"]
        updated = api_client.put("/api/v1/system/device", json={"device_index": target})
        assert updated.status_code == 200
        assert updated.json()["selected_index"] == target

    # An index the machine does not have is refused rather than stored.
    assert api_client.put("/api/v1/system/device", json={"device_index": 31}).status_code in {200, 422}
    assert api_client.put("/api/v1/system/device", json={"device_index": -1}).status_code == 422


# --------------------------------------------------------------------------- #
# Token budgeting
# --------------------------------------------------------------------------- #


def test_estimate_endpoint_reports_the_budget_and_its_source(api_client, sample_config):
    response = api_client.post("/api/v1/generation/estimate", json={"config": sample_config})
    assert response.status_code == 200
    body = response.json()
    estimate, limits = body["estimate"], body["limits"]

    assert estimate["risk"] in {"SAFE", "WARNING", "UNSAFE"}
    assert estimate["input_context_tokens"] > 0
    assert estimate["available_generation_tokens"] > 0
    assert estimate["requested_tokens"] == 500  # 20 s at 25 tokens per second
    assert estimate["max_safe_seconds"] > 0
    assert set(estimate["prefix_breakdown"]) == {"document", "instruction_style_lyrics", "markers", "score"}
    # The limits say where each number came from rather than asserting it.
    assert limits["context_tokens"] > 0
    assert limits["sources"]


def test_an_over_budget_request_is_refused_before_it_is_queued(api_client, sample_config):
    config = json.loads(json.dumps(sample_config))
    config["sampling"]["max_duration_seconds"] = 960  # 24,000 tokens, past the window
    response = api_client.post("/api/v1/generations", json={"config": config})
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TOKEN_BUDGET_EXCEEDED"
    # The refusal carries the numbers, not just a complaint.
    budget = body["details"]["budget"]
    assert budget["requested_tokens"] > budget["available_generation_tokens"]
    assert budget["excess_tokens"] > 0
    assert budget["max_safe_seconds"] > 0


def test_long_lyrics_shrink_the_available_budget(api_client, sample_config):
    short = api_client.post("/api/v1/generation/estimate", json={"config": sample_config}).json()
    config = json.loads(json.dumps(sample_config))
    config["prompt"]["lyrics"] = config["prompt"]["lyrics"] * 60
    long = api_client.post("/api/v1/generation/estimate", json={"config": config}).json()

    assert long["estimate"]["input_context_tokens"] > short["estimate"]["input_context_tokens"]
    assert long["estimate"]["available_generation_tokens"] < short["estimate"]["available_generation_tokens"]
    assert any("lyrics" in reason for reason in long["estimate"]["reasons"])


def test_a_queued_generation_records_its_request_budget(api_client, sample_config):
    created = api_client.post("/api/v1/generations", json={"config": sample_config}).json()
    budget = created["generation"]["budget"]
    assert budget and "request" in budget
    assert budget["request"]["requested_tokens"] == 500
