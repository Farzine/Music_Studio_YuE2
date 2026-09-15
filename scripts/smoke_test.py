#!/usr/bin/env python
"""End-to-end GPU smoke test.

Enqueues one short generation and runs the worker against it in-process, using
exactly the same code path the application uses. Reports elapsed time per stage,
peak VRAM and the audio file it produced.

Run with the worker environment:
    .venv-yue2/bin/python scripts/smoke_test.py --seconds 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "core"))

from yue2_studio_core.ids import new_id  # noqa: E402
from yue2_studio_core.models import GenerationJob, JobStatus  # noqa: E402
from yue2_studio_core.parameters import config_from_overrides  # noqa: E402
from yue2_studio_core.queue import FilesystemJobQueue  # noqa: E402
from yue2_studio_core.settings import get_settings  # noqa: E402
from yue2_studio_core.store import Store  # noqa: E402

DEFAULT_STYLE = "English, warm piano pop, expressive female voice, acoustic piano, light drums, 88 BPM"
DEFAULT_LYRICS = "[Verse]\nNeon fades along the lane\nFootsteps keep the time of rain\n\n[Chorus]\nLet the day come into view\nEvery road begins with you"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30.0, help="maximum duration to request")
    parser.add_argument("--seed", type=int, default=831001)
    parser.add_argument("--mode", default="full", choices=("full", "melody", "off"))
    parser.add_argument("--decoder", default="tiled", choices=("tiled", "full"))
    parser.add_argument("--style", default=DEFAULT_STYLE)
    parser.add_argument("--lyrics", default=DEFAULT_LYRICS)
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    args = parser.parse_args()

    from services.yue2_worker.worker import Worker, configure_logging

    configure_logging()
    settings = get_settings()
    store = Store(settings)
    queue = FilesystemJobQueue(store, max_concurrent_gpu_jobs=settings.max_concurrent_gpu_jobs)

    config = config_from_overrides(
        {
            "prompt": {"style": args.style, "lyrics": args.lyrics, "mode": args.mode},
            "sampling": {"seed": args.seed, "max_duration_seconds": args.seconds},
            "decoder": {"mode": args.decoder},
        }
    )
    project = store.create_project(title="Smoke test", style=args.style, lyrics=args.lyrics)
    job = GenerationJob(
        id=new_id("gen"), project_id=project.id, title="Smoke test", config=config, priority=10
    )
    store.prepare_generation_dir(project.id, job.id)
    queue.enqueue(job)
    print(f"[smoke] queued {job.id} in project {project.id}", flush=True)

    worker = Worker(once=True)
    started = time.perf_counter()
    asyncio.run(worker.run())
    elapsed = time.perf_counter() - started

    final = store.get_job(job.id)
    audio = final.audio_artifact()
    report = {
        "generation_id": final.id,
        "status": final.status.value,
        "elapsed_seconds": round(elapsed, 2),
        "timing": json.loads(final.timing.model_dump_json()),
        "truncated": final.truncated,
        "error_code": final.error_code,
        "error_message": final.error_message,
        "audio": audio.model_dump(mode="json") if audio else None,
        "request_identity": final.request_identity,
        "warnings": final.warnings,
    }
    if audio:
        path = store.absolute(audio.path)
        report["audio_exists"] = path.is_file()
        report["audio_bytes"] = path.stat().st_size if path.is_file() else 0
    peak = final.timing.gpu_peak_bytes
    if peak:
        report["gpu_peak_gib"] = round(peak / 2**30, 2)

    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered, flush=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")

    ok = final.status is JobStatus.COMPLETED and bool(report.get("audio_exists"))
    print(f"[smoke] {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
