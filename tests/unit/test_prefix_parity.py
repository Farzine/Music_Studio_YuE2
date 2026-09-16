"""The budget layer must count context exactly the way the runtime does.

A budget is only meaningful if it is measured in the model's own units, so this
compares the studio's prefix arithmetic against ``yue2.protocol.token_prefixes``
directly. It runs in the worker environment, where the runtime is importable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from yue2_studio_core.budget import INSTRUCTIONS, _prefix_tokens
from yue2_studio_core.tokenizer import get_tokenizer

pytest.importorskip("yue2", reason="the worker environment is not active")

REPO_ROOT = Path(__file__).resolve().parents[2]
MERGE_FILE = REPO_ROOT / "models" / "YuE2-3B" / "qwen.tiktoken"

pytestmark = pytest.mark.skipif(not MERGE_FILE.is_file(), reason="the checkpoint is not installed")

STYLE = "Cinematic Bengali folk-pop, warm male vocal, bamboo flute, 92 BPM"
LYRICS = "[Verse]\nসন্ধ্যা নামে নদীর পারে\n[Chorus]\nLet the day come into view"
SCORE = "X:1\nT:\nM:4/4\nL:1/16\nQ:1/4=90\nK:C\nV: Vocal clef=treble\nV: Ins clef=treble\nV: Vocal\nc4e4g4e4|\nV: Ins\nC4E4G4E4|\n"


def test_instruction_text_matches_the_runtime():
    from yue2.protocol import INSTRUCTIONS as RUNTIME

    assert INSTRUCTIONS == RUNTIME


@pytest.mark.parametrize("cot", ["full", "melody", "off"])
@pytest.mark.parametrize("abc", ["", SCORE])
def test_prefix_token_count_matches_the_runtime(cot, abc):
    from yue2.protocol import SongRequest, token_prefixes
    from yue2.tokenization_yue2 import YuE2TextTokenizer

    if abc and cot == "off":
        pytest.skip("the runtime rejects a score with cot=off")

    runtime_tokenizer = YuE2TextTokenizer(MERGE_FILE)
    request = SongRequest(style=STYLE, lyrics=LYRICS, cot=cot, abc=abc or None)
    # The budget describes the acoustic stage, whose prefix always carries the
    # score between its three markers. With no score yet that is an empty span,
    # which is a different shape from the planner's own prefix (one marker, no
    # score) — passing an empty id list asks the runtime for the right one.
    abc_ids = runtime_tokenizer.encode(abc) if abc else ([] if cot != "off" else None)
    expected = len(token_prefixes(request, runtime_tokenizer, abc_ids))

    counted, breakdown, exact, _ = _prefix_tokens(
        tokenizer=get_tokenizer(str(MERGE_FILE)), cot=cot, style=STYLE, lyrics=LYRICS, abc=abc
    )
    assert exact is True
    assert counted == expected, f"cot={cot} score={bool(abc)}: {counted} != {expected}"
    assert sum(breakdown.values()) == expected


def test_the_available_budget_is_what_the_runtime_will_accept():
    """The runtime refuses prefix + budget > context; our budget must fit."""
    from yue2.protocol import CONTEXT, SongRequest, token_prefixes
    from yue2.tokenization_yue2 import YuE2TextTokenizer

    from yue2_studio_core.budget import estimate_budget, load_model_limits

    limits = load_model_limits(
        str(REPO_ROOT / "configs"),
        str(REPO_ROOT / "models" / "YuE2-3B"),
        str(REPO_ROOT / "models" / "YuE2-Vae"),
    )
    estimate = estimate_budget(
        limits=limits,
        cot="full",
        style=STYLE,
        lyrics=LYRICS,
        requested_seconds=limits.tokens_to_seconds(1),
        abc=SCORE,
        merge_file=str(MERGE_FILE),
    )

    tokenizer = YuE2TextTokenizer(MERGE_FILE)
    request = SongRequest(style=STYLE, lyrics=LYRICS, cot="full", abc=SCORE)
    prefix = token_prefixes(request, tokenizer, tokenizer.encode(SCORE))

    # Generating the whole advertised budget stays inside the runtime's check,
    # with the safety margin and reserve still unspent.
    assert len(prefix) + estimate.available_generation_tokens <= CONTEXT
    assert CONTEXT - (len(prefix) + estimate.available_generation_tokens) >= limits.safety_margin_tokens
