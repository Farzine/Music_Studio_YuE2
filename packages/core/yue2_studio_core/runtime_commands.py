"""Worker control records in the existing filesystem store; no inference imports."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .errors import ConflictError, NotFoundError, ValidationError
from .ids import new_id
from .models import GenerationConfig, utcnow
from .store import Store, write_json_atomic


class RuntimeCommand(BaseModel):
    id: str = Field(pattern=r"^cmd_[A-Za-z0-9_-]+$")
    worker_id: str = Field(min_length=1, max_length=128)
    worker_session: str = Field(min_length=1, max_length=128)
    operation: Literal["load", "unload", "select_device", "shutdown"]
    registry_id: str | None = None
    reference: str | None = Field(default=None, min_length=1)
    protected_references: list[str] = Field(default_factory=list)
    config: GenerationConfig | None = None
    device_index: int = Field(ge=0, le=31)
    status: Literal["queued", "running", "succeeded", "failed"] = "queued"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    result: dict | None = None
    error: dict | None = None
    progress: dict | None = None

    @model_validator(mode="after")
    def model_reference_required(self):
        if self.operation in {"load", "unload"} and (not self.registry_id or not self.reference):
            raise ValueError("Model commands require a registry ID and reference.")
        return self


class RuntimeCommands:
    def __init__(self, store: Store):
        self.store = store
        self.root = store.root / "worker-commands"

    def get(self, command_id: str) -> RuntimeCommand:
        import re

        if not re.fullmatch(r"cmd_[A-Za-z0-9_-]+", command_id):
            raise ValidationError("Invalid runtime command ID.")
        path = self.root / f"{command_id}.json"
        if not path.is_file():
            raise NotFoundError("Runtime command not found.")
        try:
            command = RuntimeCommand.model_validate_json(path.read_text())
            if command.id != command_id:
                raise ValueError("Command identity mismatch")
            return command
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Runtime command {command_id} is damaged; repair it before submitting more commands.") from exc

    def list(self) -> list[RuntimeCommand]:
        return [self.get(p.stem) for p in sorted(self.root.glob("cmd_*.json"))]

    def _save(self, command: RuntimeCommand):
        command.updated_at = utcnow()
        write_json_atomic(self.root / f"{command.id}.json", command.model_dump(mode="json"))
        return command

    def enqueue(self, **values) -> RuntimeCommand:
        with self.store.queue_lock():
            return self.enqueue_locked(**values)

    def enqueue_locked(self, **values) -> RuntimeCommand:
        """Caller holds queue_lock across model admission and enqueue."""
        self.assert_accepting_locked(values["worker_id"])
        # ponytail: one pending command per worker; a backlog needs explicit
        # scheduling policy before expanding this local control channel.
        if any(c.worker_id == values["worker_id"] and c.status in {"queued", "running"} for c in self.list()):
            raise ConflictError("A runtime command is already pending for this worker. Wait for its acknowledgement.")
        return self._save(RuntimeCommand(id=new_id("cmd"), **values))

    def assert_accepting_locked(self, worker_id: str) -> None:
        if any(c.worker_id == worker_id and c.operation == "shutdown" and c.status in {"queued", "running"} for c in self.list()):
            raise ConflictError("The GPU worker is stopping. Wait for shutdown to finish before queuing new work.")

    def shutdown_requested(self, worker_id: str, session: str) -> bool:
        return any(c.worker_id == worker_id and c.worker_session == session and c.operation == "shutdown"
                   and c.status in {"queued", "running"} for c in self.list())

    def request_shutdown(self, worker_id: str, session: str) -> RuntimeCommand:
        """Shutdown must be admissible even while a load/switch is running."""
        with self.store.queue_lock():
            for command in self.list():
                if command.worker_id == worker_id and command.worker_session == session and command.operation == "shutdown":
                    return command
            return self._save(RuntimeCommand(id=new_id("cmd"), worker_id=worker_id, worker_session=session,
                                            operation="shutdown", device_index=self.store.device_index()))

    def close_session(self, worker_id: str, session: str, *, result: dict, error: dict | None = None) -> None:
        with self.store.queue_lock():
            for command in self.list():
                if command.worker_id != worker_id or command.worker_session != session or command.status not in {"queued", "running"}:
                    continue
                command.result = result
                command.error = error if command.operation == "shutdown" else {
                    "error_code": "CANCELLED", "error_message": "Worker stopped before acknowledging this command. Inspect runtime state before submitting again."}
                command.status = "failed" if command.error else "succeeded"
                self._save(command)

    def recover(self, worker_id: str, session: str) -> None:
        """Called only by the worker holding its exclusive process lease."""
        with self.store.queue_lock():
            for command in self.list():
                if command.worker_id == worker_id and command.worker_session != session and command.status in {"queued", "running"}:
                    command.status = "failed"
                    command.error = {"error_code": "CONFLICT", "error_message": "Worker restarted before acknowledging this command; inspect its runtime state and submit again."}
                    self._save(command)

    def claim(self, worker_id: str, session: str) -> RuntimeCommand | None:
        with self.store.queue_lock():
            if self.shutdown_requested(worker_id, session):
                return None  # priority stop is handled by the worker, never as a load
            for command in self.list():
                if command.worker_id == worker_id and command.worker_session == session and command.status == "queued":
                    command.status = "running"
                    return self._save(command)
        return None

    def finish(self, command: RuntimeCommand, *, result: dict, error: dict | None = None) -> RuntimeCommand:
        with self.store.queue_lock():
            current = self.get(command.id)
            if current.status != "running" or current.worker_session != command.worker_session:
                raise ConflictError("Runtime command is no longer owned by this worker invocation.")
            current.status, current.result, current.error = ("failed" if error else "succeeded"), result, error
            return self._save(current)

    def advance(self, command: RuntimeCommand, stage: str, message: str) -> None:
        """Worker-owned switch stages; UI never infers progress from timings."""
        with self.store.queue_lock():
            current = self.get(command.id)
            if current.status != "running" or current.worker_session != command.worker_session:
                raise ConflictError("Runtime command is no longer owned by this worker invocation.")
            current.progress = {"stage": stage, "message": message}
            self._save(current)
