"""Facts read out of the YuE2 runtime, not invented by this application.

``LATENT_FRAME_RATE`` comes from the VAE configuration: ``sample_rate`` 48000
divided by ``downsampling_ratio`` 1920 gives 25 latent frames per second. The
autoregressive semantic stage emits exactly one codec token per latent frame
(``yue2.nar.song_chunks`` allocates one noise row per codec token), so a token
budget is a duration budget:

    seconds = semantic_max_tokens / 25

That is why the runtime default of 9000 semantic tokens and the ComfyUI
workflow's ``max_duration = 360`` describe the same limit.
"""
from __future__ import annotations

SAMPLE_RATE = 48000
VAE_DOWNSAMPLING_RATIO = 1920
LATENT_FRAME_RATE = SAMPLE_RATE // VAE_DOWNSAMPLING_RATIO  # 25 frames per second
PROTOCOL_VERSION = "yue2-native-v1"
MANIFEST_SCHEMA_VERSION = 1

# Protocol ceilings enforced by yue2.protocol.Sampling / GenerationConfig.
MAX_SEMANTIC_TOKENS = 24000
MAX_ABC_TOKENS = 16384
CONTEXT_TOKENS = 24576
# yue2.protocol.GenerationConfig rejects anything but midpoint at this context.
FIXED_ODE_METHOD = "midpoint"
# yue2.pipeline.decode always uses a 16-frame halo; it is not a parameter.
FIXED_VAE_HALO_FRAMES = 16


def tokens_to_seconds(tokens: int) -> float:
    return tokens / LATENT_FRAME_RATE


def seconds_to_tokens(seconds: float) -> int:
    return int(round(seconds * LATENT_FRAME_RATE))
