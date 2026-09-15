"""Domain models.

These describe what the studio stores, not what any one backend accepts. The
adapter layer in ``services/yue2_worker/adapters`` translates a
:class:`GenerationConfig` into runtime calls, and refuses rather than silently
drops a parameter the active backend cannot honour.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .constants import (
    FIXED_ODE_METHOD,
    FIXED_VAE_HALO_FRAMES,
    MAX_ABC_TOKENS,
    MAX_SEMANTIC_TOKENS,
    seconds_to_tokens,
    tokens_to_seconds,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GenerationMode(str, Enum):
    """User-facing mode. ``cot`` is the native planner setting it maps to."""

    FULL = "full"
    MELODY = "melody"
    OFF = "off"
    COVER = "cover"
    SCORE_EDIT = "score_edit"

    @property
    def cot(self) -> str:
        return {
            GenerationMode.FULL: "full",
            GenerationMode.MELODY: "melody",
            GenerationMode.OFF: "off",
            # A cover conditions on a transcribed melody; the planner consumes
            # that ABC instead of writing one.
            GenerationMode.COVER: "melody",
            GenerationMode.SCORE_EDIT: "full",
        }[self]

    @property
    def requires_abc(self) -> bool:
        return self in {GenerationMode.COVER, GenerationMode.SCORE_EDIT}


class JobStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    LOADING_MODEL = "LOADING_MODEL"
    PLANNING = "PLANNING"
    GENERATING = "GENERATING"
    DECODING = "DECODING"
    POST_PROCESSING = "POST_PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

    @property
    def is_active(self) -> bool:
        return self in {
            JobStatus.LOADING_MODEL,
            JobStatus.PLANNING,
            JobStatus.GENERATING,
            JobStatus.DECODING,
            JobStatus.POST_PROCESSING,
            JobStatus.CANCEL_REQUESTED,
        }


#: Allowed transitions. The worker and the API both check against this map so a
#: stale client cannot drive a job into an impossible state.
ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.DRAFT: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.QUEUED: {JobStatus.LOADING_MODEL, JobStatus.CANCEL_REQUESTED, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.LOADING_MODEL: {JobStatus.PLANNING, JobStatus.GENERATING, JobStatus.CANCEL_REQUESTED, JobStatus.FAILED},
    JobStatus.PLANNING: {JobStatus.GENERATING, JobStatus.CANCEL_REQUESTED, JobStatus.FAILED},
    JobStatus.GENERATING: {JobStatus.DECODING, JobStatus.CANCEL_REQUESTED, JobStatus.FAILED},
    JobStatus.DECODING: {JobStatus.POST_PROCESSING, JobStatus.CANCEL_REQUESTED, JobStatus.FAILED},
    JobStatus.POST_PROCESSING: {JobStatus.COMPLETED, JobStatus.CANCEL_REQUESTED, JobStatus.FAILED},
    JobStatus.CANCEL_REQUESTED: {JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


class SeedBehavior(str, Enum):
    FIXED = "fixed"
    RANDOMIZE = "randomize"
    INCREMENT = "increment"


class DecoderMode(str, Enum):
    FULL = "full"
    TILED = "tiled"


class OutputFormat(str, Enum):
    FLAC = "flac"
    WAV = "wav"
    MP3 = "mp3"


# --------------------------------------------------------------------------- #
# Generation configuration
# --------------------------------------------------------------------------- #


class ModelConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    checkpoint: str = Field(default="", description="Local directory or HF repo id; empty means the configured default")
    revision: str | None = None
    vae: str = Field(default="standard", description="standard | legacy | path | repo id")
    vae_revision: str | None = None
    compute_backend: Literal["torch", "torch-eager", "vllm"] = "torch"
    quantization: Literal["none", "fp8"] = "none"
    offload_ar: bool = False
    memory_budget_gib: float = Field(default=40.0, ge=8.0, le=512.0)
    local_files_only: bool = True


class PromptConfig(BaseModel):
    style: str = Field(default="", max_length=4000)
    lyrics: str = Field(default="", max_length=20000)
    abc: str = Field(default="", max_length=200000)
    mode: GenerationMode = GenerationMode.FULL

    @model_validator(mode="after")
    def _check(self) -> "PromptConfig":
        if self.mode.requires_abc and not self.abc.strip():
            raise ValueError(f"mode '{self.mode.value}' requires a non-empty ABC score")
        if self.abc.strip() and self.mode == GenerationMode.OFF:
            raise ValueError("an ABC score cannot be used with Direct Audio (cot=off)")
        return self


class SamplingBlock(BaseModel):
    """Mirrors ``yue2.protocol.Sampling`` including its validation bounds."""

    temperature: float = Field(default=1.0, ge=0.0, le=5.0)
    top_p: float = Field(default=0.95, gt=0.0, le=1.0)
    top_k: int = Field(default=100, ge=1)
    repetition_penalty: float = Field(default=1.2, gt=0.0)
    penalty_window: int = Field(default=50, ge=1, le=100)
    min_tokens: int = Field(default=200, ge=0)
    max_tokens: int = Field(default=9000, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "SamplingBlock":
        if self.min_tokens > self.max_tokens:
            raise ValueError("min_tokens must not exceed max_tokens")
        return self


class PlannerConfig(SamplingBlock):
    """ABC planning stage. Defaults match ``GenerationConfig.abc``."""

    temperature: float = Field(default=0.7, ge=0.0, le=5.0)
    top_p: float = Field(default=0.9, gt=0.0, le=1.0)
    top_k: int = Field(default=30, ge=1)
    repetition_penalty: float = Field(default=1.005, gt=0.0)
    penalty_window: int = Field(default=100, ge=1, le=100)
    min_tokens: int = Field(default=32, ge=0)
    max_tokens: int = Field(default=4096, ge=1, le=MAX_ABC_TOKENS)
    #: ComfyUI's YuE2GenerateABC exposes its own seed. The native pipeline
    #: derives both stages from one request seed, so this stays None on native.
    seed: int | None = None


class SemanticConfig(SamplingBlock):
    """Acoustic-token stage plus the seed and duration budget."""

    seed: int = Field(default=831001, ge=0, lt=2**63)
    control_after_generate: SeedBehavior = SeedBehavior.FIXED
    max_tokens: int = Field(default=9000, ge=1, le=MAX_SEMANTIC_TOKENS)
    #: Authoritative duration control in the UI. ``max_tokens`` is derived from
    #: it unless ``max_tokens_override`` is set.
    max_duration_seconds: float = Field(default=360.0, gt=0.0, le=960.0)
    max_tokens_override: int | None = Field(default=None, ge=1, le=MAX_SEMANTIC_TOKENS)

    @model_validator(mode="after")
    def _derive_tokens(self) -> "SemanticConfig":
        object.__setattr__(
            self,
            "max_tokens",
            self.max_tokens_override
            if self.max_tokens_override is not None
            else max(self.min_tokens, seconds_to_tokens(self.max_duration_seconds)),
        )
        if self.max_tokens > MAX_SEMANTIC_TOKENS:
            raise ValueError(
                f"requested duration needs {self.max_tokens} semantic tokens, above the {MAX_SEMANTIC_TOKENS} limit"
            )
        return self

    @property
    def effective_duration_seconds(self) -> float:
        return tokens_to_seconds(self.max_tokens)


class SynthesisConfig(BaseModel):
    """Acoustic synthesis.

    ``cfg_scale`` and ``ode_steps`` have native equivalents. The remaining
    fields exist because the ComfyUI workflow exposes them; they are rejected
    by the native adapter rather than silently ignored.
    """

    cfg_scale: float | None = Field(default=None, ge=0.0, le=20.0)
    ode_steps: int = Field(default=32, ge=1, le=256)
    ode_method: Literal["midpoint"] = FIXED_ODE_METHOD
    # ComfyUI-only below this line.
    sampler_name: str | None = None
    scheduler: str | None = None
    denoise: float | None = Field(default=None, ge=0.0, le=1.0)
    seconds: float | None = Field(default=None, gt=0.0)
    batch_size: int | None = Field(default=None, ge=1, le=8)


class DecoderConfig(BaseModel):
    mode: DecoderMode = DecoderMode.TILED
    tile_frames: int = Field(default=1024, ge=64, le=8192, description="Native vae_core_frames")
    halo_frames: int = Field(default=FIXED_VAE_HALO_FRAMES, description="Fixed by the runtime; read-only")

    @field_validator("halo_frames")
    @classmethod
    def _fixed_halo(cls, value: int) -> int:
        if value != FIXED_VAE_HALO_FRAMES:
            raise ValueError(f"the decoder halo is fixed at {FIXED_VAE_HALO_FRAMES} frames")
        return value


class OutputConfig(BaseModel):
    format: OutputFormat = OutputFormat.FLAC
    filename_prefix: str = Field(default="YuE2", max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    #: Keep the runtime's own FLAC alongside a converted delivery file.
    keep_canonical: bool = True


class GenerationConfig(BaseModel):
    """Complete, reproducible description of one generation request."""

    model_config = ConfigDict(protected_namespaces=())

    model: ModelConfig = Field(default_factory=ModelConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    sampling: SemanticConfig = Field(default_factory=SemanticConfig)
    synthesis: SynthesisConfig = Field(default_factory=SynthesisConfig)
    decoder: DecoderConfig = Field(default_factory=DecoderConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @property
    def comfy_only_fields_in_use(self) -> dict[str, Any]:
        """Fields with no native equivalent that the user actually set."""
        synthesis = self.synthesis
        used = {
            "synthesis.sampler_name": synthesis.sampler_name,
            "synthesis.scheduler": synthesis.scheduler,
            "synthesis.denoise": synthesis.denoise,
            "synthesis.seconds": synthesis.seconds,
            "synthesis.batch_size": synthesis.batch_size,
            "planner.seed": self.planner.seed,
        }
        return {key: value for key, value in used.items() if value is not None}


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #


class SongProject(BaseModel):
    id: str
    title: str = ""
    description: str = ""
    style: str = ""
    lyrics: str = ""
    mode: GenerationMode = GenerationMode.FULL
    tags: list[str] = Field(default_factory=list)
    cover_art_path: str | None = None
    current_generation_id: str | None = None
    favorite: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProgressState(BaseModel):
    """Real backend progress only.

    ``percent`` is populated only when the stage has a genuine target (ODE
    steps, decoder chunks). Token stages report counts against a generation
    limit, which is a ceiling and not a target, so ``percent`` stays None.
    """

    stage: str = "queued"
    label: str = "Queued"
    completed: int | None = None
    total: int | None = None
    unit: str | None = None
    percent: float | None = None
    rate_per_second: float | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class TimingMetrics(BaseModel):
    queue_wait_seconds: float | None = None
    model_load_seconds: float | None = None
    planning_seconds: float | None = None
    semantic_seconds: float | None = None
    synthesis_seconds: float | None = None
    decode_seconds: float | None = None
    post_processing_seconds: float | None = None
    total_seconds: float | None = None
    gpu_peak_bytes: int | None = None
    output_seconds: float | None = None


class ArtifactRef(BaseModel):
    kind: Literal["audio", "score", "latent", "semantic", "plan", "log", "config", "manifest", "upload", "delivery"]
    path: str = Field(description="Path relative to DATA_DIR")
    bytes: int | None = None
    sha256: str | None = None
    content_type: str | None = None
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None


class GenerationJob(BaseModel):
    id: str
    project_id: str
    status: JobStatus = JobStatus.QUEUED
    priority: int = 0
    queue_position: int | None = None
    worker_id: str | None = None
    title: str = ""
    config: GenerationConfig = Field(default_factory=GenerationConfig)
    progress: ProgressState = Field(default_factory=ProgressState)
    timing: TimingMetrics = Field(default_factory=TimingMetrics)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    truncated: dict[str, bool] = Field(default_factory=dict)
    request_identity: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_guidance: str | None = None
    cancel_requested: bool = False
    favorite: bool = False
    requested_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)

    def audio_artifact(self) -> ArtifactRef | None:
        for artifact in self.artifacts:
            if artifact.kind == "audio":
                return artifact
        return None


class Preset(BaseModel):
    id: str
    name: str
    description: str = ""
    builtin: bool = False
    config: GenerationConfig = Field(default_factory=GenerationConfig)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Score(BaseModel):
    """ABC score attached to a generation: planner output plus user edits."""

    id: str
    generation_id: str
    project_id: str
    source_abc: str = ""
    edited_abc: str | None = None
    origin: Literal["planner", "upload", "transcription", "manual"] = "planner"
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Upload(BaseModel):
    id: str
    filename: str
    path: str
    bytes: int
    content_type: str
    sha256: str
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
