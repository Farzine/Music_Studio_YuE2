import pytest

from yue2_studio_core.errors import ConflictError, ValidationError
from yue2_studio_core.ids import new_id
from yue2_studio_core.models import GenerationConfig, GenerationJob
from yue2_studio_core.runtime_commands import RuntimeCommands


def enqueue(commands, **changes):
    return commands.enqueue(**dict(worker_id="local-gpu-0", worker_session="session1", operation="load",
                                   registry_id="model_fixture", reference="/models/native", config=GenerationConfig(),
                                   device_index=0, **changes))


def test_commands_serialize_claims_and_gate_new_inference(store):
    commands = RuntimeCommands(store)
    command = enqueue(commands)
    with pytest.raises(ConflictError):
        enqueue(commands)
    project = store.create_project(title="queued")
    job = store.save_job(GenerationJob(id=new_id("gen"), project_id=project.id, config=GenerationConfig()))
    assert store.claim_next_job("local-gpu-0") is None
    claimed = commands.claim("local-gpu-0", "session1")
    assert claimed.id == command.id and claimed.status == "running"
    assert commands.claim("local-gpu-0", "session1") is None
    assert store.claim_next_job("local-gpu-0") is None
    result = commands.finish(claimed, result={"lifecycle": "LOADED"})
    assert result.status == "succeeded" and result.result["lifecycle"] == "LOADED"
    assert store.claim_next_job("local-gpu-0").id == job.id
    with pytest.raises(ConflictError):
        commands.finish(claimed, result={})


@pytest.mark.parametrize("claimed", [False, True])
def test_restart_fails_old_sessions_without_replaying(store, claimed):
    commands = RuntimeCommands(store)
    command = enqueue(commands)
    if claimed:
        commands.claim("local-gpu-0", "session1")
    assert commands.claim("other-worker", "session1") is None
    commands.recover("other-worker", "session2")
    assert commands.get(command.id).status in {"queued", "running"}
    commands.recover("local-gpu-0", "session2")
    assert commands.get(command.id).status == "failed"
    assert commands.claim("local-gpu-0", "session2") is None
    enqueue(commands)


def test_damaged_command_and_unsafe_id_fail_closed(store):
    commands = RuntimeCommands(store)
    command = enqueue(commands)
    with pytest.raises(ValidationError):
        commands.get("../outside")
    (commands.root / f"{command.id}.json").write_text("broken")
    with pytest.raises(ValidationError):
        enqueue(commands)
