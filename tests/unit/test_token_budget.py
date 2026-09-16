"""Audio-token budgeting: estimation, boundaries and the generate/refuse decision."""
from __future__ import annotations

from pathlib import Path

import pytest

from yue2_studio_core.budget import (
    INSTRUCTIONS,
    PREFIX_DOCUMENT_TOKENS,
    PREFIX_MARKER_TOKENS,
    Risk,
    estimate_budget,
    load_model_limits,
    resolve_effective_tokens,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO_ROOT / "models" / "YuE2-3B"
VAE_DIR = REPO_ROOT / "models" / "YuE2-Vae"
MERGE_FILE = MODEL_DIR / "qwen.tiktoken"

STYLE = "warm piano pop, expressive female voice, 88 BPM"
LYRICS = "[Verse]\nNeon fades along the lane\n[Chorus]\nLet the day come into view"


@pytest.fixture()
def limits(data_dir):
    return load_model_limits(
        str(REPO_ROOT / "configs"),
        str(MODEL_DIR) if MODEL_DIR.is_dir() else None,
        str(VAE_DIR) if VAE_DIR.is_dir() else None,
    )


def estimate(limits, seconds: float, **kwargs):
    return estimate_budget(
        limits=limits,
        cot=kwargs.pop("cot", "full"),
        style=kwargs.pop("style", STYLE),
        lyrics=kwargs.pop("lyrics", LYRICS),
        requested_seconds=seconds,
        merge_file=str(MERGE_FILE) if MERGE_FILE.is_file() else None,
        **kwargs,
    )


# --- limits come from the model, not from a constant ----------------------- #


@pytest.mark.skipif(not MODEL_DIR.is_dir(), reason="the checkpoint is not installed")
def test_limits_are_read_from_the_model_files(limits):
    assert limits.context_tokens == 24576
    assert "max_position_embeddings" in limits.sources["context_tokens"]
    # 48000 Hz / 1920 downsampling = 25 codec tokens per second.
    assert limits.latent_frame_rate == 25
    assert "sample_rate/downsampling_ratio" in limits.sources["latent_frame_rate"]
    # Keys and values, 28 layers, 8 kv heads, head dim 128, bfloat16.
    assert limits.kv_cache_bytes_per_token == 28 * 2 * 8 * 128 * 2


def test_this_runtime_offers_no_continuation(limits):
    # Recorded as a fact about yue2-infer 0.1.6, and the reason the over-budget
    # path refuses instead of chunking. If a future runtime adds continuation,
    # this flips in configs/model-limits.json and the remedy text changes with it.
    assert limits.supports_continuation is False
    assert limits.supports_chunked_generation is False
    assert limits.capability_note


def test_seconds_and_tokens_round_trip(limits):
    assert limits.seconds_to_tokens(360) == 9000
    assert limits.tokens_to_seconds(9000) == 360
    # Rounds up, so a budget never comes out shorter than the duration asked for.
    assert limits.seconds_to_tokens(10.04) == 251


# --- prefix accounting ------------------------------------------------------ #


def test_prefix_accounts_for_document_and_marker_tokens(limits):
    result = estimate(limits, 120)
    breakdown = result.prefix_breakdown
    assert breakdown["document"] == PREFIX_DOCUMENT_TOKENS
    assert breakdown["markers"] == PREFIX_MARKER_TOKENS
    assert breakdown["score"] == 0  # not written yet
    assert result.input_context_tokens == sum(breakdown.values())


def test_lyrics_consume_the_same_window_as_the_song(limits):
    short = estimate(limits, 120)
    long = estimate(limits, 120, lyrics=LYRICS * 40)
    assert long.input_context_tokens > short.input_context_tokens
    assert long.available_generation_tokens < short.available_generation_tokens


def test_planning_modes_reserve_the_planner_ceiling_until_the_score_exists(limits):
    before = estimate(limits, 120, planner_max_tokens=4096)
    assert before.plan_reserve_tokens == 4096

    after = estimate(limits, 120, abc="X:1\nT:\nM:4/4\nL:1/16\nQ:1/4=90\nK:C\n")
    assert after.plan_reserve_tokens == 0
    # Dropping the reservation frees almost all of it back to the song.
    assert after.available_generation_tokens > before.available_generation_tokens + 3000


def test_direct_audio_reserves_nothing_for_a_score(limits):
    assert estimate(limits, 120, cot="off").plan_reserve_tokens == 0


@pytest.mark.skipif(not MERGE_FILE.is_file(), reason="the tokenizer is not installed")
def test_counting_uses_the_checkpoint_tokenizer(limits):
    assert estimate(limits, 120).exact_tokenisation is True


def test_a_missing_tokenizer_is_declared_not_hidden(limits):
    result = estimate_budget(
        limits=limits,
        cot="full",
        style=STYLE,
        lyrics=LYRICS,
        requested_seconds=120,
        merge_file="/nonexistent/qwen.tiktoken",
    )
    assert result.exact_tokenisation is False
    assert result.tokenisation_note
    assert result.input_context_tokens > 0  # still usable, just approximate


# --- boundaries ------------------------------------------------------------- #


def test_a_comfortable_request_is_safe(limits):
    assert estimate(limits, 120).risk is Risk.SAFE


def test_exactly_at_the_limit_still_fits(limits):
    available = estimate(limits, 1).available_generation_tokens
    exact = estimate(limits, limits.tokens_to_seconds(available))
    assert exact.requested_tokens == available
    assert exact.risk is not Risk.UNSAFE
    assert exact.excess_tokens == 0


def test_one_token_over_the_limit_is_unsafe(limits):
    available = estimate(limits, 1).available_generation_tokens
    over = estimate(limits, limits.tokens_to_seconds(available + 1))
    assert over.risk is Risk.UNSAFE
    assert over.excess_tokens >= 1
    assert over.reasons and over.remedies


def test_approaching_the_limit_warns(limits):
    available = estimate(limits, 1).available_generation_tokens
    near = estimate(limits, limits.tokens_to_seconds(int(available * 0.95)))
    assert near.risk is Risk.WARNING
    assert near.reasons


def test_an_unsafe_request_says_what_to_change(limits):
    over = estimate(limits, 960)
    assert over.risk is Risk.UNSAFE
    joined = " ".join(over.remedies)
    assert "duration" in joined
    # No continuation exists here, and the remedies must not pretend otherwise.
    assert "no continuation" in joined


def test_kv_cache_cost_scales_with_the_budget(limits):
    small = estimate(limits, 120)
    large = estimate(limits, 600)
    assert large.kv_cache_bytes > small.kv_cache_bytes
    # Guidance runs a second branch, which doubles the cache.
    branched = estimate(limits, 120, cfg_branches=2)
    assert branched.kv_cache_bytes == pytest.approx(small.kv_cache_bytes * 2, rel=0.01)


# --- the decision ----------------------------------------------------------- #


def decide(limits, cap_seconds, planned_seconds, fit_to_plan=True):
    result = estimate(limits, cap_seconds, abc="X:1", planned_seconds=planned_seconds)
    return resolve_effective_tokens(
        limits=limits,
        estimate=result,
        requested_tokens=limits.seconds_to_tokens(cap_seconds),
        fit_to_plan=fit_to_plan,
    )


def test_a_song_shorter_than_the_limit_generates_unchanged(limits):
    decision = decide(limits, 360, 85)
    assert decision.allowed
    assert decision.adjustment is None
    assert decision.effective_tokens == decision.requested_tokens


def test_a_song_longer_than_the_limit_raises_it_and_reports_the_change(limits):
    decision = decide(limits, 60, 200)
    assert decision.allowed
    assert decision.adjustment is not None
    assert decision.adjustment["requested"] == 60
    assert decision.adjustment["effective"] >= 200
    # The requested value is kept beside the effective one; nothing is silent.
    assert "raised" in decision.adjustment["reason"]
    assert decision.effective_tokens > decision.requested_tokens


def test_respecting_the_limit_refuses_rather_than_truncating(limits):
    decision = decide(limits, 60, 200, fit_to_plan=False)
    assert not decision.allowed
    assert decision.refusal["code"] == "INCOMPLETE_TOKEN_LIMIT"
    assert "cuts off part way" in decision.refusal["message"]


def test_a_song_too_long_for_the_context_is_refused(limits):
    decision = decide(limits, 60, 5000)
    assert not decision.allowed
    assert decision.refusal["code"] == "TOKEN_BUDGET_EXCEEDED"
    assert "one pass" in decision.refusal["message"]


def test_a_limit_beyond_the_context_is_refused_before_the_runtime_would(limits):
    # yue2.sampling.generate_tokens raises on prefix + budget > context. This
    # reaches the same conclusion first, with numbers the user can act on.
    result = estimate(limits, 960)
    decision = resolve_effective_tokens(
        limits=limits, estimate=result, requested_tokens=limits.seconds_to_tokens(960), fit_to_plan=True
    )
    assert not decision.allowed
    assert decision.refusal["code"] == "TOKEN_BUDGET_EXCEEDED"
