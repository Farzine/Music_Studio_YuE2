"""Manifest contents and ABC validation."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from yue2_studio_core.abc import AbcValidationError, compare, try_validate, validate
from yue2_studio_core.ids import new_id
from yue2_studio_core.manifest import build_manifest, identity
from yue2_studio_core.models import ArtifactRef, GenerationJob, JobStatus, utcnow
from yue2_studio_core.parameters import default_config

# A real planner output, captured from a generation on this machine. The
# dialect is narrow (native ``X:1``, blank ``T:``, Vocal and Ins voices), so a
# hand-written score is not a valid fixture.
SCORE = (Path(__file__).resolve().parents[1] / "fixtures" / "planner_score.abc").read_text(encoding="utf-8")


def reharmonise(text: str) -> str:
    """Swap every triad for its seventh, leaving every note untouched."""
    return re.sub(r'"([A-G][b#]?)(m?)"', lambda m: f'"{m.group(1)}{m.group(2)}7"', text)


def test_identity_is_stable_and_order_independent():
    assert identity({"a": 1, "b": 2}) == identity({"b": 2, "a": 1})
    assert identity({"a": 1}) != identity({"a": 2})


def test_manifest_records_request_effective_config_weights_and_hardware(data_dir):
    job = GenerationJob(
        id=new_id("gen"),
        project_id=new_id("prj"),
        config=default_config(),
        status=JobStatus.COMPLETED,
        finished_at=utcnow(),
        request_identity="abc123",
    )
    job.artifacts.append(ArtifactRef(kind="audio", path="projects/x/audio/final.flac", bytes=10))
    manifest = build_manifest(
        job,
        runtime={"torch": "2.10.0", "yue2-infer": "0.1.6"},
        weights={"mot": {"config_sha256": "deadbeef"}},
        effective_config={"cot": "full", "cfg_scale": 1.0},
        hardware={"name": "RTX A6000", "total_bytes": 51_539_607_552},
        artifacts=[artifact.model_dump(mode="json") for artifact in job.artifacts],
    )
    assert manifest["schema_version"] == 1
    assert manifest["generation_id"] == job.id
    assert manifest["finished_at"] is not None
    # The request is preserved as asked for, separately from what took effect.
    assert manifest["request"]["sampling"]["seed"] == job.config.sampling.seed
    assert manifest["effective_config"]["cot"] == "full"
    assert manifest["weights"]["mot"]["config_sha256"] == "deadbeef"
    assert manifest["hardware"]["name"] == "RTX A6000"
    assert manifest["hardware"]["host"]["python"]
    assert manifest["manifest_identity"]


def test_manifest_identity_changes_with_the_request(data_dir):
    def make(seed: int) -> str:
        config = default_config()
        config.sampling.seed = seed
        job = GenerationJob(id=new_id("gen"), project_id=new_id("prj"), config=config)
        return build_manifest(
            job, runtime={}, weights={}, effective_config={}, hardware={}, artifacts=[]
        )["manifest_identity"]

    assert make(1) != make(2)


def test_valid_score_parses():
    report = validate(SCORE)
    assert report["bpm"] == 90
    assert set(report["voices"]) == {"Vocal", "Ins"}


def test_invalid_score_is_rejected_with_a_reason():
    with pytest.raises(AbcValidationError):
        validate("this is not ABC notation")
    ok, _, error = try_validate("")
    assert ok is False and error


def test_reharmonisation_preserves_the_melody():
    result = compare(SCORE, reharmonise(SCORE))
    # Harmony may change; notes, timing, meter and tempo may not.
    assert result["match"] is True


def test_changing_notes_is_reported():
    # Raise one sounding pitch by a step; harmony and timing are untouched, so
    # only the melody invariant can fail.
    lines = SCORE.splitlines()
    for index, line in enumerate(lines):
        match = re.search(r"(?<![A-Za-z\'])([ceg])([\',]*)(\d*)", line)
        if "|" in line and match:
            replacement = {"c": "d", "e": "f", "g": "a"}[match.group(1)]
            lines[index] = line[: match.start(1)] + replacement + line[match.start(1) + 1 :]
            break
    else:
        raise AssertionError("the fixture contains no mutable pitch")
    result = compare(SCORE, "\n".join(lines) + "\n")
    assert result["match"] is False
