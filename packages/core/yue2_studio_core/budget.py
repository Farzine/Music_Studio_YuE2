"""Audio-token budgeting.

One place where every token calculation lives, so the API, the worker and the
frontend cannot disagree about what fits.

The constraint this models is real and specific. YuE2's acoustic stage is
autoregressive over codec tokens: one token per latent frame, 25 frames per
second of audio. ``yue2.sampling.generate_tokens`` refuses outright when

    len(prefix) + sampling.max_tokens > context

so the prefix — instruction, style, lyrics and the ABC score — is subtracted
from the same window the song has to fit in. There is no implicit truncation
and no continuation API, so that window is a hard ceiling on song length.

Two estimates are produced, and the difference matters:

* **request** — before anything runs. The score does not exist yet, so the
  planner's whole ceiling is reserved. Conservative by construction.
* **plan** — after the score is written. Its exact token cost and its intended
  duration are both known, so this estimate is the one decisions are made on.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path

from .tokenizer import get_tokenizer

#: Copied from ``yue2.protocol.INSTRUCTIONS``. Counted as part of the prefix, so
#: it has to match the runtime exactly; a test asserts that it still does.
INSTRUCTIONS = {
    "off": "Generate music with codec tokens from the given conditions.",
    "melody": (
        "Generate a melody-only ABC transcription without chord symbols, then generate music "
        "with codec tokens from the given conditions."
    ),
    "full": (
        "Generate a chord-annotated ABC transcription, then generate music with codec tokens "
        "from the given conditions."
    ),
}

#: ``token_prefixes`` adds one end-of-document token before the text and three
#: markers after it (ABC_START, ABC_END, MUSIC_START).
PREFIX_DOCUMENT_TOKENS = 1
PREFIX_MARKER_TOKENS = 3


class Risk(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    UNSAFE = "UNSAFE"


@dataclass(frozen=True)
class ModelLimits:
    """What one checkpoint can actually do, preferring values read from it."""

    model_id: str
    protocol: str
    context_tokens: int
    latent_frame_rate: int
    reserved_tokens: int
    safety_margin_tokens: int
    warning_threshold: float
    plan_length_tolerance: float
    supports_continuation: bool
    supports_chunked_generation: bool
    capability_note: str
    #: Bytes of key/value cache the autoregressive stage preallocates per token
    #: of prefix-plus-budget, so a larger budget has a real, predictable cost.
    kv_cache_bytes_per_token: int = 0
    sources: dict = field(default_factory=dict)

    def tokens_to_seconds(self, tokens: int) -> float:
        return tokens / self.latent_frame_rate

    def seconds_to_tokens(self, seconds: float) -> int:
        return int(math.ceil(seconds * self.latent_frame_rate))

    def to_dict(self) -> dict:
        return asdict(self)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=8)
def load_model_limits(
    configs_dir: str, model_dir: str | None = None, vae_dir: str | None = None, family: str = "yue2"
) -> ModelLimits:
    """Limits for a checkpoint, read from the model files where possible.

    ``max_position_embeddings`` and the decoder's sample rate over its
    downsampling ratio are authoritative; the values in configs/model-limits.json
    are only used when those files cannot be read.
    """
    document = _read_json(Path(configs_dir) / "model-limits.json") or {}
    defaults = document.get("defaults", {})
    declared = (document.get("models") or {}).get(family, {})

    context = int(declared.get("context_tokens", 24576))
    frame_rate = int(declared.get("latent_frame_rate", 25))
    sources: dict = {"context_tokens": "configs/model-limits.json", "latent_frame_rate": "configs/model-limits.json"}

    if model_dir:
        config = _read_json(Path(model_dir) / "config.json")
        value = (config or {}).get("max_position_embeddings")
        if isinstance(value, int) and value > 0:
            context = value
            sources["context_tokens"] = f"{model_dir}/config.json:max_position_embeddings"

    kv_bytes_per_token = 0
    if model_dir:
        config = _read_json(Path(model_dir) / "config.json") or {}
        layers = config.get("num_hidden_layers")
        kv_heads = config.get("num_key_value_heads")
        head_dim = config.get("head_dim")
        if all(isinstance(value, int) and value > 0 for value in (layers, kv_heads, head_dim)):
            # keys and values, bfloat16
            kv_bytes_per_token = layers * 2 * kv_heads * head_dim * 2
            sources["kv_cache_bytes_per_token"] = f"{model_dir}/config.json"

    if vae_dir:
        config = _read_json(Path(vae_dir) / "config.json")
        rate = (config or {}).get("sample_rate")
        ratio = (config or {}).get("downsampling_ratio")
        if isinstance(rate, int) and isinstance(ratio, int) and ratio > 0 and rate % ratio == 0:
            frame_rate = rate // ratio
            sources["latent_frame_rate"] = f"{vae_dir}/config.json:sample_rate/downsampling_ratio"

    return ModelLimits(
        model_id=declared.get("model_id", "m-a-p/YuE2-3B"),
        protocol=declared.get("protocol", "yue2-native-v1"),
        context_tokens=context,
        latent_frame_rate=frame_rate,
        reserved_tokens=int(declared.get("reserved_tokens", defaults.get("reserved_tokens", 8))),
        safety_margin_tokens=int(
            declared.get("safety_margin_tokens", defaults.get("safety_margin_tokens", 256))
        ),
        warning_threshold=float(defaults.get("warning_threshold", 0.85)),
        plan_length_tolerance=float(defaults.get("plan_length_tolerance", 1.15)),
        supports_continuation=bool(declared.get("supports_continuation", False)),
        supports_chunked_generation=bool(declared.get("supports_chunked_generation", False)),
        capability_note=declared.get("capability_note", ""),
        kv_cache_bytes_per_token=kv_bytes_per_token,
        sources=sources,
    )


@dataclass
class BudgetEstimate:
    """What a request needs against what the model can give it."""

    stage: str  # "request" before planning, "plan" once the score exists
    risk: Risk
    exact_tokenisation: bool
    tokenisation_note: str | None

    context_tokens: int
    input_context_tokens: int
    prefix_breakdown: dict
    plan_reserve_tokens: int
    reserved_tokens: int
    safety_margin_tokens: int
    available_generation_tokens: int

    requested_tokens: int
    requested_seconds: float
    max_safe_tokens: int
    max_safe_seconds: float

    planned_seconds: float | None = None
    planned_tokens: int | None = None

    #: Key/value cache the acoustic stage will preallocate for this budget.
    #: Doubled when guidance runs a second branch.
    kv_cache_bytes: int = 0
    cfg_branches: int = 1

    supports_continuation: bool = False
    supports_chunked_generation: bool = False
    reasons: list[str] = field(default_factory=list)
    remedies: list[str] = field(default_factory=list)

    @property
    def fits(self) -> bool:
        return self.risk is not Risk.UNSAFE

    @property
    def excess_tokens(self) -> int:
        return max(0, self.requested_tokens - self.available_generation_tokens)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["risk"] = self.risk.value
        payload["excess_tokens"] = self.excess_tokens
        return payload


def _prefix_tokens(
    *,
    tokenizer,
    cot: str,
    style: str,
    lyrics: str,
    abc: str,
) -> tuple[int, dict, bool, str | None]:
    """Reproduce ``yue2.protocol.token_prefixes`` without building the ids."""
    instruction = INSTRUCTIONS.get(cot, INSTRUCTIONS["full"])
    # SongRequest.text(): "{instruction}\n[Tags]\n{style}\n[Lyrics]\n{lyrics}\n"
    text = f"{instruction}\n[Tags]\n{style}\n[Lyrics]\n{lyrics}\n"
    counted = tokenizer.count(text)
    abc_counted = tokenizer.count(abc) if abc.strip() and cot != "off" else tokenizer.count("")

    total = PREFIX_DOCUMENT_TOKENS + counted.tokens + PREFIX_MARKER_TOKENS + abc_counted.tokens
    breakdown = {
        "document": PREFIX_DOCUMENT_TOKENS,
        "instruction_style_lyrics": counted.tokens,
        "markers": PREFIX_MARKER_TOKENS,
        "score": abc_counted.tokens,
    }
    return total, breakdown, counted.exact, counted.reason


def estimate_budget(
    *,
    limits: ModelLimits,
    cot: str,
    style: str,
    lyrics: str,
    requested_seconds: float,
    abc: str = "",
    planner_max_tokens: int = 4096,
    merge_file: str | None = None,
    planned_seconds: float | None = None,
    cfg_branches: int = 1,
) -> BudgetEstimate:
    """Work out whether a request fits, and say why when it does not.

    ``abc`` empty with a planning mode means the score has not been written
    yet, so the planner's full ceiling is reserved. Once the score exists, pass
    it: the reservation disappears and the numbers become exact.
    """
    tokenizer = get_tokenizer(merge_file)
    prefix, breakdown, exact, note = _prefix_tokens(
        tokenizer=tokenizer, cot=cot, style=style, lyrics=lyrics, abc=abc
    )

    planning = cot != "off"
    # Before the score exists its cost is unknown, so reserve what the planner
    # is allowed to write. After it exists the reservation is zero because the
    # real cost is already inside `prefix`.
    plan_reserve = planner_max_tokens if (planning and not abc.strip()) else 0

    available = (
        limits.context_tokens
        - prefix
        - plan_reserve
        - limits.reserved_tokens
        - limits.safety_margin_tokens
    )
    available = max(0, available)

    requested_tokens = limits.seconds_to_tokens(requested_seconds)
    planned_tokens = (
        limits.seconds_to_tokens(planned_seconds * limits.plan_length_tolerance)
        if planned_seconds is not None
        else None
    )

    reasons: list[str] = []
    remedies: list[str] = []

    if requested_tokens > available:
        risk = Risk.UNSAFE
        reasons.append(
            f"The requested {requested_seconds:.0f} s needs {requested_tokens:,} audio tokens, "
            f"but only {available:,} are available in the model's {limits.context_tokens:,}-token window."
        )
    elif requested_tokens > available * limits.warning_threshold:
        risk = Risk.WARNING
        reasons.append(
            f"The requested {requested_seconds:.0f} s uses {requested_tokens / available:.0%} of the "
            f"available {available:,} audio tokens."
        )
    else:
        risk = Risk.SAFE

    if plan_reserve:
        reasons.append(
            f"{plan_reserve:,} tokens are held back for the score the planner has not written yet; "
            "the exact figure is recalculated once it has."
        )

    # Three percent of the window is roughly thirty seconds of song, which is
    # the point at which the text's cost is worth mentioning.
    if breakdown["instruction_style_lyrics"] > limits.context_tokens * 0.03:
        reasons.append(
            f"The style and lyrics occupy {breakdown['instruction_style_lyrics']:,} tokens of the "
            f"{limits.context_tokens:,}-token window, about "
            f"{limits.tokens_to_seconds(breakdown['instruction_style_lyrics']):.0f} s of song."
        )
        remedies.append("Shorten the lyrics; every token they use is one the song cannot.")

    if risk is not Risk.SAFE:
        remedies.append(
            f"Reduce the maximum duration to {limits.tokens_to_seconds(available):.0f} s or less."
        )
        if planning:
            remedies.append("Fewer or shorter sections in the lyrics produce a shorter planned song.")
        if limits.supports_continuation:
            remedies.append("Generate the song in continued segments.")
        else:
            remedies.append(
                "This runtime generates a song in one pass and offers no continuation or chunking, "
                "so a longer song cannot be assembled from segments."
            )

    if planned_tokens is not None and planned_tokens > requested_tokens:
        reasons.append(
            f"The written score runs {planned_seconds:.0f} s, which needs about {planned_tokens:,} "
            f"tokens — more than the {requested_tokens:,} the duration limit allows."
        )

    kv_cache_bytes = (prefix + requested_tokens) * limits.kv_cache_bytes_per_token * max(1, cfg_branches)

    return BudgetEstimate(
        stage="plan" if planned_seconds is not None else "request",
        risk=risk,
        exact_tokenisation=exact,
        tokenisation_note=note,
        context_tokens=limits.context_tokens,
        input_context_tokens=prefix,
        prefix_breakdown=breakdown,
        plan_reserve_tokens=plan_reserve,
        reserved_tokens=limits.reserved_tokens,
        safety_margin_tokens=limits.safety_margin_tokens,
        available_generation_tokens=available,
        requested_tokens=requested_tokens,
        requested_seconds=float(requested_seconds),
        max_safe_tokens=available,
        max_safe_seconds=limits.tokens_to_seconds(available),
        planned_seconds=planned_seconds,
        planned_tokens=planned_tokens,
        kv_cache_bytes=kv_cache_bytes,
        cfg_branches=max(1, cfg_branches),
        supports_continuation=limits.supports_continuation,
        supports_chunked_generation=limits.supports_chunked_generation,
        reasons=reasons,
        remedies=remedies,
    )


@dataclass
class TokenDecision:
    """What budget to generate with, once the score's length is known."""

    effective_tokens: int
    requested_tokens: int
    estimate: BudgetEstimate
    adjustment: dict | None = None
    #: Set when generation must not start. The caller raises; this stays pure.
    refusal: dict | None = None

    @property
    def allowed(self) -> bool:
        return self.refusal is None


def resolve_effective_tokens(
    *,
    limits: ModelLimits,
    estimate: BudgetEstimate,
    requested_tokens: int,
    fit_to_plan: bool,
) -> TokenDecision:
    """Decide the acoustic token budget for a run, or refuse it.

    Called once the score exists, so ``estimate.planned_tokens`` is the length
    the model actually intends. Three outcomes:

    * the limit already covers the song — generate as asked;
    * the song is longer than the limit but fits the context — raise the limit
      so it can finish, and report the change;
    * the song cannot fit at all, or the user asked for the limit to be
      respected — refuse before generating, rather than produce a fragment.

    Raising the limit cannot make a song longer than the model intended: the
    model emits its end token when the song is done. It only stops it being cut
    off. The cost is a proportionally larger key/value cache.

    Pure by design: it returns a refusal rather than raising, so the same
    decision can be unit-tested and reused by every backend.
    """
    available = estimate.available_generation_tokens
    needed = estimate.planned_tokens

    if requested_tokens > available:
        return TokenDecision(
            effective_tokens=requested_tokens,
            requested_tokens=requested_tokens,
            estimate=estimate,
            refusal={
                "code": "TOKEN_BUDGET_EXCEEDED",
                "message": (
                    f"The duration limit needs {requested_tokens:,} audio tokens but only "
                    f"{available:,} fit beside this song's style, lyrics and score in the model's "
                    f"{limits.context_tokens:,}-token window."
                ),
            },
        )

    if needed is None or needed <= requested_tokens:
        return TokenDecision(requested_tokens, requested_tokens, estimate)

    planned = estimate.planned_seconds or 0.0
    if not fit_to_plan:
        return TokenDecision(
            effective_tokens=requested_tokens,
            requested_tokens=requested_tokens,
            estimate=estimate,
            refusal={
                "code": "INCOMPLETE_TOKEN_LIMIT",
                "message": (
                    f"The written score runs {planned:.0f} s, which needs about {needed:,} audio "
                    f"tokens, but the duration limit allows {requested_tokens:,}. Generation was "
                    "stopped before it started rather than producing a song that cuts off part way."
                ),
            },
        )

    if needed > available:
        remedy = (
            "Generate the song in continued segments."
            if limits.supports_continuation
            else (
                "This runtime generates a song in one pass and has no continuation or chunking "
                "mechanism, so a longer song cannot be assembled from segments."
            )
        )
        return TokenDecision(
            effective_tokens=requested_tokens,
            requested_tokens=requested_tokens,
            estimate=estimate,
            refusal={
                "code": "TOKEN_BUDGET_EXCEEDED",
                "message": (
                    f"The written score runs {planned:.0f} s and needs about {needed:,} audio tokens, "
                    f"but only {available:,} fit in the model's context window alongside the style, "
                    f"lyrics and score. {remedy}"
                ),
            },
        )

    return TokenDecision(
        effective_tokens=needed,
        requested_tokens=requested_tokens,
        estimate=estimate,
        adjustment={
            "parameter": "sampling.max_duration_seconds",
            "requested": round(limits.tokens_to_seconds(requested_tokens), 1),
            "effective": round(limits.tokens_to_seconds(needed), 1),
            "unit": "seconds",
            "reason": (
                f"The written score runs {planned:.0f} s. The limit was raised so the song reaches "
                "its own ending instead of stopping part way."
            ),
        },
    )
