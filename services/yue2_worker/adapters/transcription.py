"""Calling the SheetSage2 transcription service.

SheetSage2 and YuE2 pin incompatible torch and transformers versions, so they
never share an interpreter. The service runs as a subprocess in its own
environment and hands back a JSON report plus a score file.

The subprocess is launched with an argument list, never a shell string, and the
only user-controlled value that reaches it is a path the store produced.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.settings import Settings
from .base import signal_child

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]


class TranscriptionResult:
    def __init__(self, payload: dict) -> None:
        self.abc: str = payload["abc"]
        self.warnings: list[str] = list(payload.get("warnings") or [])
        self.duration_seconds: float | None = payload.get("duration_seconds")
        self.elapsed_seconds: float | None = payload.get("elapsed_seconds")
        self.score_path: str | None = payload.get("score_path")


class SheetSage2Transcriber:
    """Runs the transcription service and turns its failures into studio errors."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def available(self) -> tuple[bool, str | None]:
        if not (self.settings.sheetsage2_path / "model.safetensors").is_file():
            return False, f"SheetSage2 weights are missing at {self.settings.sheetsage2_path}."
        if not self.settings.sheetsage2_python.is_file():
            return False, f"The SheetSage2 environment is missing at {self.settings.sheetsage2_python}."
        if not self.settings.ffmpeg_path.is_file():
            return False, "FFmpeg was not found; SheetSage2 needs it to decode audio."
        return True, None

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        device_index: int,
        cancelled=None,
        on_progress=None,
    ) -> TranscriptionResult:
        if cancelled is not None and cancelled():
            raise StudioError(ErrorCode.CANCELLED, "Cancelled before transcription started.", stage="transcribing")
        ok, reason = self.available()
        if not ok:
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, reason or "Cover is unavailable.", stage="transcribing")

        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "transcription.json"

        environment = dict(os.environ)
        # Pin the child to the selected card; inside the child it is device 0.
        visible = environment.get("CUDA_VISIBLE_DEVICES")
        if visible is not None:
            devices = [entry.strip() for entry in visible.split(",")]
            if device_index not in range(len(devices)) or not devices[device_index] or devices[device_index] == "-1":
                raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, f"GPU {device_index} is unavailable under CUDA_VISIBLE_DEVICES.", stage="transcribing")
            environment["CUDA_VISIBLE_DEVICES"] = devices[device_index]
        else:
            environment["CUDA_VISIBLE_DEVICES"] = str(device_index)
        ffmpeg_dir = self.settings.ffmpeg_path.parent
        environment["PATH"] = f"{ffmpeg_dir}{os.pathsep}{environment.get('PATH', '')}"
        environment["PYTHONPATH"] = str(REPO_ROOT)
        environment.setdefault("HF_HUB_OFFLINE", "1" if self.settings.yue2_local_files_only else "0")

        command = [
            str(self.settings.sheetsage2_python),
            "-m",
            "services.sheetsage2_worker.transcribe",
            "--audio",
            str(audio_path),
            "--output",
            str(output_dir),
            "--model",
            str(self.settings.sheetsage2_path),
            "--report",
            str(report_path),
            "--device",
            "cuda:0",
        ]
        if self.settings.yue2_local_files_only:
            command.append("--local-files-only")

        logger.info("transcribing %s on cuda:%s", audio_path.name, device_index)
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
        )

        # The encoder reports "Window n/total" as it goes; forward that as real
        # progress rather than inventing a percentage.
        stderr_lines, reader_errors = deque(maxlen=50), []
        def pump(stream, progress=False):
            try:
                for line in stream:
                    line = line.strip()
                    if not progress:
                        stderr_lines.append(line)
                    elif on_progress and line.startswith("Window "):
                        try:
                            completed, total = line.removeprefix("Window ").split("/")
                            on_progress(int(completed), int(total))
                        except (ValueError, IndexError):
                            pass
            except Exception as exc:
                reader_errors.append(exc)
        readers = []
        try:
            for stream, progress in ((process.stdout, True), (process.stderr, False)):
                reader = threading.Thread(target=pump, args=(stream, progress), daemon=True, name="sheetsage2-stream")
                reader.start()
                readers.append(reader)
            deadline = started + self.settings.sheetsage2_timeout_seconds
            while process.poll() is None:
                if cancelled is not None and cancelled():
                    raise StudioError(ErrorCode.CANCELLED, "Cancelled while transcribing.", stage="transcribing")
                if reader_errors:
                    raise reader_errors[0]
                if time.monotonic() > deadline:
                    raise StudioError(ErrorCode.AUDIO_INPUT_ERROR, f"Transcription exceeded {self.settings.sheetsage2_timeout_seconds}s and was stopped.", stage="transcribing")
                time.sleep(0.1)
        finally:
            # Always reap, including timeout, callback/startup errors and cancel.
            signal_child(process)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                signal_child(process, force=True)
                process.wait(timeout=10)
            finally:
                if process.poll() is not None:
                    signal_child(process, force=True)  # inherited pipe handles/descendants
                    for reader in readers:
                        reader.join(timeout=5)
                    for stream in (process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
        if reader_errors:
            raise reader_errors[0]
        stderr = "\n".join(stderr_lines)

        payload: dict = {}
        if report_path.is_file():
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}

        if process.returncode != 0 or payload.get("status") != "complete":
            detail = payload.get("error") or stderr.strip().splitlines()[-1:] or ["no detail"]
            message = detail if isinstance(detail, str) else detail[0]
            raise StudioError(
                ErrorCode.AUDIO_INPUT_ERROR,
                f"The reference audio could not be transcribed: {message}",
                stage="transcribing",
                details={"exit_code": process.returncode, "report": str(report_path)},
            )

        if not payload.get("abc", "").strip():
            raise StudioError(
                ErrorCode.INVALID_ABC,
                "Transcription produced an empty score. Try a recording with a clearer melody.",
                stage="transcribing",
            )
        return TranscriptionResult(payload)
