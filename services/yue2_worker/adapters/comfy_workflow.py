"""ComfyUI workflow adapter — compatibility and reference layer.

This exists so a studio configuration can also be executed by a ComfyUI server
that has the YuE2 nodes installed, and so the mapping between the two worlds
stays honest. It is not the primary path and it does not duplicate ComfyUI
internals: it patches widget values on the reference graph, submits the prompt,
and collects the audio the graph saved.

The native runtime exposes stages; ComfyUI exposes node-level execution
progress. That difference is declared in the capability document rather than
papered over with a made-up percentage.
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from yue2_studio_core.constants import LATENT_FRAME_RATE
from yue2_studio_core.errors import ErrorCode, StudioError
from yue2_studio_core.models import GenerationConfig, JobStatus
from yue2_studio_core.parameters import load_workflow_mapping
from yue2_studio_core.settings import Settings

from .base import (
    AudioTokensResult,
    BackendResult,
    DecodedAudio,
    GenerationContext,
    PlanResult,
)

#: Studio parameter -> (workflow node type, widget name). Derived from the
#: generated mapping file so it cannot drift from the reference workflow.
def _widget_targets() -> dict[str, tuple[str, str]]:
    targets: dict[str, tuple[str, str]] = {}
    for entry in load_workflow_mapping()["parameters"]:
        if entry["comfy_node_type"] and entry["comfy_widget"]:
            targets[entry["parameter"]] = (entry["comfy_node_type"], entry["comfy_widget"])
    return targets


class ComfyWorkflowBackend:
    name = "comfy"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = (settings.comfy_api_url or "").rstrip("/")
        self.workflow_path = Path(settings._resolve(settings.comfy_workflow_path))
        self._client_id = str(uuid.uuid4())
        self._prompt_id: str | None = None
        self._audio: np.ndarray | None = None
        self._sample_rate = 48000
        self._graph: dict | None = None

    # -- capabilities ------------------------------------------------------ #

    async def get_capabilities(self) -> dict:
        return {
            "backend": self.name,
            "modes": ["full", "melody", "off"],
            "server": self.base_url or None,
            "workflow": str(self.workflow_path),
        }

    async def validate_config(self, config: GenerationConfig) -> list[str]:
        if not self.base_url:
            raise StudioError(
                ErrorCode.INVALID_CONFIG,
                "COMFY_API_URL is not set, so the ComfyUI backend cannot be used.",
                stage="validation",
            )
        if not self.workflow_path.is_file():
            raise StudioError(
                ErrorCode.INVALID_CONFIG,
                f"The reference workflow {self.workflow_path} was not found.",
                stage="validation",
            )
        missing = await self._missing_node_types()
        if missing:
            raise StudioError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "The ComfyUI server does not provide the YuE2 nodes this workflow needs: "
                + ", ".join(sorted(missing)),
                stage="validation",
                details={"missing_nodes": sorted(missing)},
            )
        return [
            "The ComfyUI backend reports node-level progress only, and cancels by interrupting the "
            "running prompt rather than at a token boundary."
        ]

    async def _object_info(self) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/object_info")
            response.raise_for_status()
            return response.json()

    async def _missing_node_types(self) -> set[str]:
        graph = self._load_graph()
        required = {node["type"] for node in graph["nodes"] if node.get("mode", 0) != 4 and node["type"] != "Note"}
        try:
            available = set(await self._object_info())
        except Exception as exc:
            raise StudioError(
                ErrorCode.INVALID_CONFIG,
                f"The ComfyUI server at {self.base_url} could not be reached: {exc}",
                stage="validation",
            ) from exc
        return {name for name in required if name not in available and name != "PrimitiveNode"}

    def _load_graph(self) -> dict:
        if self._graph is None:
            self._graph = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        return copy.deepcopy(self._graph)

    # -- graph patching ---------------------------------------------------- #

    def build_prompt(self, config: GenerationConfig) -> dict:
        """Apply the studio configuration onto the reference graph.

        Only parameters the mapping marks as belonging to a ComfyUI widget are
        written. Anything else is left exactly as the reference workflow has it.
        """
        graph = self._load_graph()
        targets = _widget_targets()
        values: dict[str, Any] = {
            "prompt.style": config.prompt.style,
            "prompt.lyrics": config.prompt.lyrics,
            "prompt.abc": config.prompt.abc,
            "prompt.mode": config.prompt.mode.cot,
            "sampling.seed": config.sampling.seed,
            "sampling.temperature": config.sampling.temperature,
            "sampling.top_p": config.sampling.top_p,
            "sampling.top_k": config.sampling.top_k,
            "sampling.repetition_penalty": config.sampling.repetition_penalty,
            "sampling.max_duration_seconds": config.sampling.effective_duration_seconds,
            "planner.max_tokens": config.planner.max_tokens,
            "planner.seed": config.planner.seed if config.planner.seed is not None else config.sampling.seed,
            "synthesis.ode_steps": config.synthesis.ode_steps,
            "synthesis.cfg_scale": config.synthesis.cfg_scale if config.synthesis.cfg_scale is not None else 1,
            "synthesis.sampler_name": config.synthesis.sampler_name or "dpm_2",
            "synthesis.scheduler": config.synthesis.scheduler or "sgm_uniform",
            "synthesis.denoise": config.synthesis.denoise if config.synthesis.denoise is not None else 1,
            "synthesis.seconds": config.synthesis.seconds or config.sampling.effective_duration_seconds,
            "synthesis.batch_size": config.synthesis.batch_size or 1,
            "decoder.tile_frames": config.decoder.tile_frames,
            "decoder.halo_frames": config.decoder.halo_frames,
            "output.format": config.output.format.value,
            "output.filename_prefix": f"audio/{config.output.filename_prefix}",
            "model.checkpoint": Path(config.model.checkpoint).name if config.model.checkpoint else None,
        }
        by_id = {node["id"]: node for node in graph["nodes"]}
        for parameter, value in values.items():
            if value is None or parameter not in targets:
                continue
            node_type, widget = targets[parameter]
            for node in by_id.values():
                named = node.get("widgets_values_named")
                if node["type"] == node_type and named and widget in named:
                    named[widget] = value
                    order = list(named)
                    node["widgets_values"] = [named[key] for key in order]
        return self._to_api_prompt(graph)

    @staticmethod
    def _to_api_prompt(graph: dict) -> dict:
        """Convert the saved UI graph to the /prompt API shape."""
        outputs: dict[str, Any] = {}
        link_sources = {link[0]: (link[1], link[2]) for link in graph.get("links", [])}
        for node in graph["nodes"]:
            if node["type"] in {"Note", "PrimitiveNode"} or node.get("mode", 0) == 4:
                continue
            inputs: dict[str, Any] = {}
            named = node.get("widgets_values_named") or {}
            inputs.update(named)
            for slot in node.get("inputs", []):
                link_id = slot.get("link")
                if link_id is None:
                    continue
                source = link_sources.get(link_id)
                if source is None:
                    continue
                source_node, source_slot = source
                inputs[slot["name"]] = [str(source_node), source_slot]
            outputs[str(node["id"])] = {"class_type": node["type"], "inputs": inputs}
        return outputs

    # -- execution --------------------------------------------------------- #

    async def prepare(self, config: GenerationConfig, context: GenerationContext) -> None:
        import httpx

        context.reporter.begin(JobStatus.LOADING_MODEL, "submitting", "Submitting to ComfyUI")
        prompt = self.build_prompt(config)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/prompt", json={"prompt": prompt, "client_id": self._client_id}
            )
            if response.status_code >= 400:
                raise StudioError(
                    ErrorCode.INFERENCE_FAILED,
                    f"ComfyUI rejected the prompt: {response.text}",
                    stage="submitting",
                )
            self._prompt_id = response.json()["prompt_id"]

    async def generate_plan(self, context: GenerationContext) -> PlanResult:
        # ComfyUI runs the whole graph as one unit; the plan is not separable.
        return PlanResult(abc=None, abc_token_count=0, truncated=False, timing={}, handle=None)

    async def generate_audio(self, context: GenerationContext, plan: PlanResult) -> AudioTokensResult:
        import httpx

        context.reporter.begin(JobStatus.GENERATING, "executing", "Running the ComfyUI graph")
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=60) as client:
            while True:
                if context.cancelled():
                    await client.post(f"{self.base_url}/interrupt")
                    raise StudioError(ErrorCode.CANCELLED, "Interrupted the ComfyUI prompt.", stage="executing")
                history = await client.get(f"{self.base_url}/history/{self._prompt_id}")
                payload = history.json() if history.status_code == 200 else {}
                entry = payload.get(self._prompt_id)
                if entry:
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        raise StudioError(
                            ErrorCode.INFERENCE_FAILED,
                            f"ComfyUI reported an error: {json.dumps(status)[:800]}",
                            stage="executing",
                        )
                    if status.get("completed"):
                        self._outputs = entry.get("outputs", {})
                        break
                await asyncio.sleep(1.0)
        return AudioTokensResult(
            latents=np.zeros((0, 64), dtype=np.float32),
            semantic_token_count=0,
            truncated=False,
            timing={"execute_seconds": time.perf_counter() - started},
            handle=None,
        )

    async def decode_audio(self, context: GenerationContext, tokens: AudioTokensResult) -> DecodedAudio:
        import io

        import httpx
        import soundfile

        context.reporter.begin(JobStatus.DECODING, "fetching", "Fetching audio from ComfyUI")
        reference = None
        for node_output in getattr(self, "_outputs", {}).values():
            for item in node_output.get("audio", []):
                reference = item
                break
        if reference is None:
            raise StudioError(ErrorCode.DECODER_FAILED, "The ComfyUI graph produced no audio.", stage="fetching")
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.get(f"{self.base_url}/view", params=reference)
            response.raise_for_status()
            data, rate = soundfile.read(io.BytesIO(response.content), dtype="float32", always_2d=True)
        return DecodedAudio(audio=data, sample_rate=int(rate), timing={})

    async def finalise(self, context, plan, tokens, audio) -> BackendResult:
        from yue2_studio_core.manifest import identity

        config = json.loads(context.config.model_dump_json())
        effective = {
            "backend": "comfy",
            "server": self.base_url,
            "workflow": str(self.workflow_path),
            "prompt_id": self._prompt_id,
            "generation": config,
            "validation_status": "comfy-compatibility-layer",
        }
        weights = {"comfy_checkpoint": context.config.model.checkpoint}
        return BackendResult(
            plan=plan,
            tokens=tokens,
            audio=audio,
            effective_config=effective,
            weights=weights,
            runtime={"backend": "comfy", "latent_frame_rate": LATENT_FRAME_RATE},
            request_identity=identity({"config": config, "weights": weights}),
            semantic_tokens=None,
        )

    async def cancel(self, job_id: str) -> None:
        import httpx

        if not self.base_url:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{self.base_url}/interrupt")

    async def shutdown(self) -> None:
        return None
