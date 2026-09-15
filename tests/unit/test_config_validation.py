"""Configuration validation and the duration/token relationship."""
from __future__ import annotations

import pytest

from yue2_studio_core.constants import LATENT_FRAME_RATE, seconds_to_tokens
from yue2_studio_core.errors import ValidationError
from yue2_studio_core.models import GenerationConfig, GenerationMode
from yue2_studio_core.parameters import config_from_overrides, default_config


def test_latent_frame_rate_matches_the_vae_configuration():
    # 48000 Hz / 1920 downsampling ratio. This is why 9000 semantic tokens and
    # the workflow's max_duration of 360 describe the same limit.
    assert LATENT_FRAME_RATE == 25
    assert seconds_to_tokens(360) == 9000


def test_duration_drives_the_token_budget(data_dir):
    config = config_from_overrides({"sampling": {"max_duration_seconds": 40.0}})
    assert config.sampling.max_tokens == 1000
    assert config.sampling.effective_duration_seconds == 40.0


def test_explicit_token_override_wins(data_dir):
    config = config_from_overrides(
        {"sampling": {"max_duration_seconds": 40.0, "max_tokens_override": 2000}}
    )
    assert config.sampling.max_tokens == 2000
    assert config.sampling.effective_duration_seconds == 80.0


def test_defaults_match_the_runtime_protocol(data_dir):
    config = default_config()
    assert config.sampling.temperature == 1.0
    assert config.sampling.top_p == 0.95
    assert config.sampling.top_k == 100
    assert config.sampling.repetition_penalty == 1.2
    assert config.planner.temperature == 0.7
    assert config.planner.max_tokens == 4096
    assert config.synthesis.ode_steps == 32
    assert config.synthesis.ode_method == "midpoint"


@pytest.mark.parametrize(
    "overrides",
    [
        {"sampling": {"temperature": 9.0}},
        {"sampling": {"top_p": 0.0}},
        {"sampling": {"top_k": 0}},
        {"sampling": {"penalty_window": 500}},
        {"planner": {"max_tokens": 999999}},
        {"synthesis": {"cfg_scale": 99.0}},
        {"decoder": {"halo_frames": 64}},
    ],
)
def test_out_of_range_values_are_rejected(data_dir, overrides):
    with pytest.raises(ValidationError):
        config_from_overrides(overrides)


def test_score_modes_require_an_abc_score():
    with pytest.raises(Exception):
        GenerationConfig.model_validate({"prompt": {"style": "x", "lyrics": "y", "mode": "score_edit"}})


def test_direct_audio_rejects_a_score():
    with pytest.raises(Exception):
        GenerationConfig.model_validate({"prompt": {"style": "x", "lyrics": "y", "mode": "off", "abc": "X:1"}})


def test_mode_maps_to_the_native_cot_setting():
    assert GenerationMode.FULL.cot == "full"
    assert GenerationMode.MELODY.cot == "melody"
    assert GenerationMode.OFF.cot == "off"
    # A cover conditions on a transcribed melody rather than planning one.
    assert GenerationMode.COVER.cot == "melody"
    assert GenerationMode.SCORE_EDIT.cot == "full"
