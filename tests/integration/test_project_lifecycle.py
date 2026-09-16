"""Project lifecycle: rename, settings, history, regeneration, deletion.

The rule these all exist to protect: a project is a container that can change,
and a generation is a historical record that cannot. Regenerating adds a take;
it never edits the one it came from.
"""
from __future__ import annotations

import asyncio

import pytest

from yue2_studio_core.store import Store


def run_worker_once() -> None:
    from services.yue2_worker.worker import Worker

    asyncio.run(Worker(once=True).run())


def create(api_client, config, **body):
    response = api_client.post("/api/v1/generations", json={"config": config, **body})
    assert response.status_code == 201, response.text
    return response.json()


# -- project management ----------------------------------------------------- #


def test_a_project_can_be_renamed(api_client, sample_config):
    project_id = create(api_client, sample_config, title="First name")["project"]["id"]

    renamed = api_client.patch(f"/api/v1/projects/{project_id}", json={"title": "  Second   name  "})
    assert renamed.status_code == 200
    # Surrounding and repeated whitespace is normalised, not preserved.
    assert renamed.json()["title"] == "Second name"

    assert api_client.get(f"/api/v1/projects/{project_id}").json()["project"]["title"] == "Second name"


@pytest.mark.parametrize("title", ["", "   ", "\n\t"])
def test_a_project_cannot_be_renamed_to_nothing(api_client, sample_config, title):
    project_id = create(api_client, sample_config, title="Keep me")["project"]["id"]

    refused = api_client.patch(f"/api/v1/projects/{project_id}", json={"title": title})
    assert refused.status_code == 422
    assert refused.json()["error_code"] == "INVALID_CONFIG"
    # The old name survives a refused rename.
    assert api_client.get(f"/api/v1/projects/{project_id}").json()["project"]["title"] == "Keep me"


def test_a_project_name_has_an_upper_bound(api_client, sample_config):
    project_id = create(api_client, sample_config, title="Bounded")["project"]["id"]
    refused = api_client.patch(f"/api/v1/projects/{project_id}", json={"title": "x" * 500})
    assert refused.status_code == 422


def test_the_settings_editor_opens_on_the_latest_take_then_on_the_saved_settings(api_client, sample_config):
    created = create(api_client, sample_config, title="Editable")
    project_id = created["project"]["id"]

    opened = api_client.get(f"/api/v1/projects/{project_id}/config").json()
    # A project created by generating starts out described by that take.
    assert opened["source"] == "project"
    assert opened["config"]["prompt"]["style"] == sample_config["prompt"]["style"]

    saved = api_client.put(
        f"/api/v1/projects/{project_id}/config",
        json={"config": {"prompt": {**sample_config["prompt"], "style": "edited style"},
                         "sampling": {"max_duration_seconds": 42.0}}},
    )
    assert saved.status_code == 200
    assert saved.json()["style"] == "edited style"

    reopened = api_client.get(f"/api/v1/projects/{project_id}/config").json()
    assert reopened["source"] == "project"
    assert reopened["config"]["sampling"]["max_duration_seconds"] == 42.0


def test_editing_project_settings_never_rewrites_a_finished_take(api_client, sample_config):
    created = create(api_client, sample_config, title="History is fixed")
    project_id = created["project"]["id"]
    generation_id = created["generation"]["id"]
    before = api_client.get(f"/api/v1/generations/{generation_id}").json()["generation"]["config"]

    api_client.put(
        f"/api/v1/projects/{project_id}/config",
        json={"config": {"prompt": {**sample_config["prompt"], "style": "something else entirely"},
                         "sampling": {"seed": 999999}}},
    )

    after = api_client.get(f"/api/v1/generations/{generation_id}").json()["generation"]["config"]
    assert after == before


def test_an_invalid_project_setting_is_refused_rather_than_stored(api_client, sample_config):
    project_id = create(api_client, sample_config)["project"]["id"]
    refused = api_client.put(
        f"/api/v1/projects/{project_id}/config",
        json={"config": {"sampling": {"temperature": 99.0}}},
    )
    assert refused.status_code == 422
    assert api_client.get(f"/api/v1/projects/{project_id}/config").json()["config"]["sampling"]["temperature"] != 99.0


def test_the_project_list_carries_the_counts_it_displays(api_client, sample_config):
    project_id = create(api_client, sample_config, title="Counted")["project"]["id"]
    create(api_client, sample_config, project_id=project_id)

    listing = api_client.get("/api/v1/projects").json()["items"]
    entry = next(item for item in listing if item["id"] == project_id)
    assert entry["generation_count"] == 2
    assert entry["latest_generation_id"]


# -- versions and lineage --------------------------------------------------- #


def test_each_take_in_a_project_gets_the_next_version_number(api_client, sample_config):
    first = create(api_client, sample_config, title="Versions")
    project_id = first["project"]["id"]
    assert first["generation"]["version"] == 1

    second = create(api_client, sample_config, project_id=project_id)["generation"]
    third = create(api_client, sample_config, project_id=project_id)["generation"]
    assert [second["version"], third["version"]] == [2, 3]

    # A different project counts from one again.
    other = create(api_client, sample_config, title="Separate")["generation"]
    assert other["version"] == 1


def test_a_version_number_is_not_reused_after_a_deletion(api_client, sample_config):
    first = create(api_client, sample_config, title="No reuse")
    project_id = first["project"]["id"]
    second = create(api_client, sample_config, project_id=project_id)["generation"]
    # A running take cannot be deleted, so let the queue drain first.
    run_worker_once()
    run_worker_once()

    assert api_client.delete(f"/api/v1/generations/{second['id']}").status_code == 200

    third = create(api_client, sample_config, project_id=project_id)["generation"]
    assert third["version"] == 3, "version 2 was deleted; reusing the number would reorder the history"


def test_regenerating_creates_a_new_take_and_leaves_the_original_untouched(api_client, sample_config):
    original = create(api_client, sample_config, title="Original")
    project_id = original["project"]["id"]
    original_id = original["generation"]["id"]

    edited = {
        "prompt": {**sample_config["prompt"], "lyrics": "[Verse]\nA different second verse"},
        "sampling": {"max_duration_seconds": 30.0, "seed": 777},
    }
    new_take = create(
        api_client,
        edited,
        project_id=project_id,
        parent_generation_id=original_id,
        title="Original",
    )["generation"]

    assert new_take["id"] != original_id
    assert new_take["version"] == 2
    assert new_take["parent_generation_id"] == original_id
    assert new_take["config"]["sampling"]["seed"] == 777

    kept = api_client.get(f"/api/v1/generations/{original_id}").json()["generation"]
    assert kept["config"]["sampling"]["seed"] == sample_config["sampling"]["seed"]
    assert kept["config"]["prompt"]["lyrics"] == sample_config["prompt"]["lyrics"]
    assert kept["parent_generation_id"] is None


def test_retry_and_duplicate_record_where_they_came_from(api_client, sample_config):
    original = create(api_client, sample_config, title="Lineage")
    original_id = original["generation"]["id"]
    run_worker_once()

    retried = api_client.post(f"/api/v1/generations/{original_id}/retry").json()
    assert retried["parent_generation_id"] == original_id

    duplicated = api_client.post(f"/api/v1/generations/{original_id}/duplicate", json={}).json()
    assert duplicated["parent_generation_id"] == original_id


def test_a_parent_from_another_project_is_refused(api_client, sample_config):
    first = create(api_client, sample_config, title="One")
    second = create(api_client, sample_config, title="Two")

    refused = api_client.post(
        "/api/v1/generations",
        json={
            "config": sample_config,
            "project_id": second["project"]["id"],
            "parent_generation_id": first["generation"]["id"],
        },
    )
    assert refused.status_code == 422
    assert "same project" in refused.json()["error_message"]


# -- history ---------------------------------------------------------------- #


def test_the_history_lists_every_take_newest_first(api_client, sample_config):
    first = create(api_client, sample_config, title="Ordered")
    project_id = first["project"]["id"]
    create(api_client, sample_config, project_id=project_id)
    create(api_client, sample_config, project_id=project_id)

    generations = api_client.get(f"/api/v1/projects/{project_id}").json()["generations"]
    assert [item["version"] for item in generations] == [3, 2, 1]


def test_deleting_one_take_leaves_the_others_alone(api_client, sample_config):
    first = create(api_client, sample_config, title="Selective")
    project_id = first["project"]["id"]
    second = create(api_client, sample_config, project_id=project_id)["generation"]
    third = create(api_client, sample_config, project_id=project_id)["generation"]
    for _ in range(3):
        run_worker_once()

    assert api_client.delete(f"/api/v1/generations/{second['id']}").json()["deleted"] is True

    remaining = api_client.get(f"/api/v1/projects/{project_id}").json()["generations"]
    assert {item["id"] for item in remaining} == {first["generation"]["id"], third["id"]}
    assert api_client.get(f"/api/v1/generations/{second['id']}").status_code == 404


def test_an_empty_history_is_a_normal_state(api_client, sample_config):
    created = create(api_client, sample_config, title="Emptied")
    project_id = created["project"]["id"]
    run_worker_once()
    assert api_client.delete(f"/api/v1/generations/{created['generation']['id']}").status_code == 200

    body = api_client.get(f"/api/v1/projects/{project_id}").json()
    assert body["generations"] == []
    # The project survives, and no longer points at a generation that is gone.
    assert body["project"]["current_generation_id"] is None


# -- project deletion -------------------------------------------------------- #


def test_deleting_a_project_removes_its_takes_and_their_files(api_client, sample_config, data_dir):
    created = create(api_client, sample_config, title="Doomed")
    project_id = created["project"]["id"]
    generation_id = created["generation"]["id"]
    run_worker_once()

    directory = data_dir / "projects" / project_id
    assert directory.is_dir()

    report = api_client.delete(f"/api/v1/projects/{project_id}")
    assert report.status_code == 200
    body = report.json()
    assert body["deleted"] is True
    assert body["complete"] is True
    assert body["generations_removed"] == 1
    assert body["generation_ids"] == [generation_id]

    assert not directory.exists()
    assert not (data_dir / "jobs" / f"{generation_id}.json").exists()
    assert api_client.get(f"/api/v1/projects/{project_id}").status_code == 404
    assert api_client.get(f"/api/v1/generations/{generation_id}").status_code == 404


def test_deleting_a_project_leaves_other_projects_alone(api_client, sample_config):
    doomed = create(api_client, sample_config, title="Doomed")
    survivor = create(api_client, sample_config, title="Survivor")

    api_client.delete(f"/api/v1/projects/{doomed['project']['id']}")

    assert api_client.get(f"/api/v1/projects/{survivor['project']['id']}").status_code == 200
    assert api_client.get(f"/api/v1/generations/{survivor['generation']['id']}").status_code == 200


def test_a_project_with_a_queued_take_is_not_deleted(api_client, sample_config):
    created = create(api_client, sample_config, title="Busy")
    project_id = created["project"]["id"]

    refused = api_client.delete(f"/api/v1/projects/{project_id}")
    assert refused.status_code == 409
    assert api_client.get(f"/api/v1/projects/{project_id}").status_code == 200


def test_deleting_a_missing_project_is_a_404(api_client):
    assert api_client.delete("/api/v1/projects/prj_doesnotexist000").status_code == 404


# -- download --------------------------------------------------------------- #


def test_the_download_picker_offers_only_formats_this_machine_can_write(api_client, sample_config):
    job_id = create(api_client, sample_config, title="Downloadable")["generation"]["id"]
    run_worker_once()

    body = api_client.get(f"/api/v1/artifacts/{job_id}/formats").json()
    assert body["source"]["format"] == "flac"
    assert body["default_filename"].startswith("YuE2-Downloadable-v1")

    by_id = {entry["id"]: entry for entry in body["formats"]}
    assert by_id["flac"]["is_source"] is True
    for entry in body["formats"]:
        assert entry["supported"] or entry["reason"], f"{entry['id']} is neither usable nor explained"


def test_a_converted_download_is_a_new_file_and_the_master_is_untouched(api_client, sample_config, data_dir):
    job_id = create(api_client, sample_config, title="Converted")["generation"]["id"]
    run_worker_once()

    formats = api_client.get(f"/api/v1/artifacts/{job_id}/formats").json()
    if not next(entry for entry in formats["formats"] if entry["id"] == "mp3")["supported"]:
        pytest.skip("this machine has no MP3 encoder")

    store = Store()
    master = store.absolute(
        api_client.get(f"/api/v1/generations/{job_id}").json()["generation"]["artifacts"][0]["path"]
    )
    before = master.read_bytes()

    response = api_client.get(
        f"/api/v1/artifacts/{job_id}/download", params={"format": "mp3", "filename": "My Song"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert "My%20Song.mp3" in response.headers["content-disposition"]
    assert response.content[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xfa")

    assert master.read_bytes() == before, "the master must never be re-encoded"
    # The temporary copy is removed once the response has been sent.
    leftovers = list((data_dir / "tmp" / "downloads").glob("*")) if (data_dir / "tmp" / "downloads").is_dir() else []
    assert leftovers == []


def test_a_download_filename_cannot_escape_its_own_file(api_client, sample_config):
    job_id = create(api_client, sample_config)["generation"]["id"]
    run_worker_once()

    response = api_client.get(
        f"/api/v1/artifacts/{job_id}/download", params={"filename": "../../../etc/passwd"}
    )
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "/" not in disposition.split("filename")[-1]
    assert "passwd.flac" in disposition


def test_an_unknown_download_format_is_refused(api_client, sample_config):
    job_id = create(api_client, sample_config)["generation"]["id"]
    run_worker_once()

    refused = api_client.get(f"/api/v1/artifacts/{job_id}/download", params={"format": "aiff"})
    assert refused.status_code == 422
    assert "aiff" in refused.json()["error_message"]


def test_formats_for_a_generation_with_no_audio_is_a_404(api_client, sample_config):
    job_id = create(api_client, sample_config)["generation"]["id"]
    assert api_client.get(f"/api/v1/artifacts/{job_id}/formats").status_code == 404
