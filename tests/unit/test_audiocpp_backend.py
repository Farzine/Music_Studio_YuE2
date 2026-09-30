"""The GGUF adapter must pass the selected device and return real artifacts."""
from __future__ import annotations

import asyncio
import json
import threading

import numpy as np
import soundfile as sf

from yue2_studio_core.ids import new_id
from yue2_studio_core.models import GenerationConfig, GenerationJob, JobStatus
from yue2_studio_core.settings import Settings
from yue2_studio_core.store import Store, write_json_atomic

from services.yue2_worker.adapters.audiocpp import AudioCppBackend
from services.yue2_worker.adapters.base import GenerationContext


def test_gguf_cli_uses_selected_gpu_and_returns_score_and_audio(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    for name in ("yue2-3b-q8_0.gguf", "yue2-vae-f16.gguf"):
        (model / name).write_bytes(b"model")
    write_json_atomic(model / "studio-model.json", {"filename": "yue2-3b-q8_0.gguf", "revision": "abc"})
    source = tmp_path / "source.wav"
    sf.write(source, np.zeros((4800, 2), dtype=np.float32), 48000)
    cli = tmp_path / "audiocpp_cli"
    cli.write_text(
        '#!/usr/bin/env bash\n'
        'while [[ $# -gt 0 ]]; do\n'
        '  case "$1" in\n'
        '    --device) device="$2"; shift 2;;\n'
        '    --out) out="$2"; shift 2;;\n'
        '    --out-dir) dir="$2"; shift 2;;\n'
        '    *) shift;;\n'
        '  esac\n'
        'done\n'
        'printf "%s" "$device" > "$dir/device.txt"\n'
        f'cp "{source}" "$out"\n'
        'printf "X:1\\nT:Test\\nM:4/4\\nK:C\\nCDEF|" > "$dir/score.abc"\n'
        'printf "[1,2,3]" > "$dir/semantic.json"\n',
        encoding="utf-8",
    )
    cli.chmod(0o755)
    settings = Settings(data_dir=str(tmp_path / "data"), audiocpp_cli_path=str(cli))
    store = Store(settings)
    store.write_runtime_settings({"device_index": 2})
    config = GenerationConfig.model_validate({"model": {"checkpoint": str(model)}, "prompt": {"style": "pop", "lyrics": "hello"}})
    job = GenerationJob(id=new_id("job"), project_id=new_id("prj"), config=config)
    store.save_job(job)
    store.prepare_generation_dir(job.project_id, job.id)

    class Reporter:
        def begin(self, *args, **kwargs):
            pass

    context = GenerationContext(job_id=job.id, config=config, reporter=Reporter(), cancel_event=threading.Event())
    backend = AudioCppBackend(settings, store)
    store.write_runtime_settings({"device_index": 1})  # change while this job is active

    async def run():
        await backend.validate_config(config)
        await backend.prepare(config, context)
        plan = await backend.generate_plan(context)
        tokens = await backend.generate_audio(context, plan)
        audio = await backend.decode_audio(context, tokens)
        result = await backend.finalise(context, plan, tokens, audio)
        return plan, audio, result

    plan, audio, result = asyncio.run(run())
    assert "CDEF" in plan.abc
    assert audio.audio.shape == (4800, 2)
    assert result.runtime["backend"] == "audiocpp"
    assert json.loads((store.generation_dir(job.project_id, job.id) / "audiocpp/semantic.json").read_text()) == [1, 2, 3]
    assert (store.generation_dir(job.project_id, job.id) / "audiocpp/device.txt").read_text() == "2"
