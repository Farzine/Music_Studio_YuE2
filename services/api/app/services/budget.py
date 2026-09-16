"""Token budgeting for the API process.

Wraps :mod:`yue2_studio_core.budget` with the paths this installation is
configured with, so routes and validation share one answer.
"""
from __future__ import annotations

from pathlib import Path

from yue2_studio_core.abc import score_duration_seconds
from yue2_studio_core.budget import BudgetEstimate, ModelLimits, estimate_budget, load_model_limits
from yue2_studio_core.models import GenerationConfig, GenerationMode
from yue2_studio_core.settings import Settings


class BudgetService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _model_dir(self, config: GenerationConfig | None) -> str | None:
        from yue2_studio_core.models import DEFAULT_MODEL

        reference = self.settings.model_reference
        if config is not None and config.model.checkpoint not in {DEFAULT_MODEL, ""}:
            reference = config.model.checkpoint
        path = Path(reference)
        return str(path) if path.is_dir() else None

    def limits(self, config: GenerationConfig | None = None) -> ModelLimits:
        vae = Path(self.settings.vae_reference)
        return load_model_limits(
            str(self.settings.configs_path),
            self._model_dir(config),
            str(vae) if vae.is_dir() else None,
        )

    def merge_file(self, config: GenerationConfig | None = None) -> str | None:
        model_dir = self._model_dir(config)
        if not model_dir:
            return None
        candidate = Path(model_dir) / "qwen.tiktoken"
        return str(candidate) if candidate.is_file() else None

    def estimate(self, config: GenerationConfig) -> BudgetEstimate:
        """Pre-generation estimate for a request, before anything has run."""
        limits = self.limits(config)
        supplied_abc = config.prompt.abc if config.prompt.mode is not GenerationMode.COVER else ""
        return estimate_budget(
            limits=limits,
            cot=config.prompt.mode.cot,
            style=config.prompt.style,
            lyrics=config.prompt.lyrics,
            requested_seconds=config.sampling.effective_duration_seconds,
            abc=supplied_abc,
            planner_max_tokens=config.planner.max_tokens,
            merge_file=self.merge_file(config),
            # A score supplied with the request already states its own length,
            # so the decision can be made now instead of after planning.
            planned_seconds=score_duration_seconds(supplied_abc) if supplied_abc.strip() else None,
        )
