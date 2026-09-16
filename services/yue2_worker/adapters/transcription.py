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
from pathlib import Path

from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.settings import Settings

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
        ok, reason = self.available()
        if not ok:
            raise StudioError(ErrorCode.UNSUPPORTED_CAPABILITY, reason or "Cover is unavailable.", stage="transcribing")

        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "transcription.json"

        environment = dict(os.environ)
        # Pin the child to the selected card; inside the child it is device 0.
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
        )

        # The encoder reports "Window n/total" as it goes; forward that as real
        # progress rather than inventing a percentage.
        def pump() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                line = line.strip()
                if on_progress and line.startswith("Window "):
                    try:
                        completed, total = line.removeprefix("Window ").split("/")
                        on_progress(int(completed), int(total))
                    except (ValueError, IndexError):
                        pass

        reader = threading.Thread(target=pump, daemon=True, name="sheetsage2-progress")
        reader.start()

        deadline = started + self.settings.sheetsage2_timeout_seconds
        while process.poll() is None:
            if cancelled is not None and cancelled():
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise StudioError(ErrorCode.CANCELLED, "Cancelled while transcribing.", stage="transcribing")
            if time.monotonic() > deadline:
                process.kill()
                raise StudioError(
                    ErrorCode.AUDIO_INPUT_ERROR,
                    f"Transcription exceeded {self.settings.sheetsage2_timeout_seconds}s and was stopped.",
                    stage="transcribing",
                )
            time.sleep(0.5)
        reader.join(timeout=5)
        stderr = (process.stderr.read() if process.stderr else "") or ""

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
