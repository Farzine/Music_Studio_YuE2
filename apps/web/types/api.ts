/** Shapes served by the FastAPI backend. Mirrors packages/core models. */

export type JobStatus =
  | "DRAFT"
  | "QUEUED"
  | "LOADING_MODEL"
  | "TRANSCRIBING"
  | "PLANNING"
  | "GENERATING"
  | "DECODING"
  | "POST_PROCESSING"
  | "COMPLETED"
  | "INCOMPLETE"
  | "FAILED"
  | "CANCEL_REQUESTED"
  | "CANCELLED";

export type GenerationMode = "full" | "melody" | "off" | "cover" | "score_edit";

export interface ProgressState {
  stage: string;
  label: string;
  completed: number | null;
  total: number | null;
  unit: string | null;
  /** Null whenever the stage has no genuine target; never a fabricated number. */
  percent: number | null;
  rate_per_second: number | null;
  updated_at: string;
}

export interface TimingMetrics {
  queue_wait_seconds: number | null;
  model_load_seconds: number | null;
  planning_seconds: number | null;
  semantic_seconds: number | null;
  synthesis_seconds: number | null;
  decode_seconds: number | null;
  post_processing_seconds: number | null;
  total_seconds: number | null;
  gpu_peak_bytes: number | null;
  output_seconds: number | null;
}

export interface ArtifactRef {
  kind: string;
  path: string;
  bytes: number | null;
  sha256: string | null;
  content_type: string | null;
  duration_seconds: number | null;
  sample_rate: number | null;
  channels: number | null;
}

export interface GenerationConfig {
  model: Record<string, unknown>;
  prompt: {
    style: string;
    lyrics: string;
    abc: string;
    mode: GenerationMode;
    reference_upload_id: string | null;
  };
  planner: Record<string, unknown>;
  sampling: Record<string, unknown> & {
    seed: number;
    max_duration_seconds: number;
    max_tokens: number;
  };
  synthesis: Record<string, unknown>;
  decoder: Record<string, unknown>;
  output: { format: string; filename_prefix: string; keep_canonical: boolean };
}

export interface GenerationJob {
  id: string;
  project_id: string;
  /** Position within the project, from 1. Assigned once and never reused. */
  version: number;
  /** The take this one was started from, when it came from Regenerate. */
  parent_generation_id: string | null;
  status: JobStatus;
  priority: number;
  queue_position: number | null;
  worker_id: string | null;
  title: string;
  config: GenerationConfig;
  progress: ProgressState;
  timing: TimingMetrics;
  artifacts: ArtifactRef[];
  warnings: string[];
  truncated: Record<string, boolean>;
  budget: {
    request?: BudgetEstimate;
    plan?: BudgetEstimate;
    limits?: ModelLimits;
    semantic?: {
      budget_tokens: number;
      tokens_generated: number;
      termination_reason: string | null;
    };
  } | null;
  termination_reason: string | null;
  effective_adjustments: {
    parameter: string;
    requested: number;
    effective: number;
    unit: string;
    reason: string;
  }[];
  request_identity: string | null;
  error_code: string | null;
  error_message: string | null;
  error_guidance: string | null;
  cancel_requested: boolean;
  favorite: boolean;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  failed_at: string | null;
  updated_at: string;
}

export interface SongProject {
  id: string;
  title: string;
  description: string;
  style: string;
  lyrics: string;
  mode: GenerationMode;
  tags: string[];
  current_generation_id: string | null;
  /** Settings a new take in this project starts from; null until edited. */
  default_config: GenerationConfig | null;
  generation_counter: number;
  favorite: boolean;
  created_at: string;
  updated_at: string;
}

/** A project as the list view receives it, with its counts precomputed. */
export interface ProjectSummary extends SongProject {
  generation_count: number;
  playable_count: number;
  latest_generation_id: string | null;
  latest_generation_at: string | null;
}

export interface ProjectConfigResponse {
  config: GenerationConfig;
  /** Where the editor's starting values came from. */
  source: "project" | "latest_generation" | "defaults";
}

export interface ProjectDeleteReport {
  deleted: boolean;
  project_id: string;
  title: string;
  generations_removed: number;
  generation_ids: string[];
  had_generations: number;
  complete: boolean;
  failures: { path: string; error: string }[];
}

/** One downloadable format, with whether this machine can actually write it. */
export interface DownloadFormat {
  id: string;
  label: string;
  extension: string;
  mime: string;
  lossless: boolean;
  description: string;
  supported: boolean;
  reason: string | null;
  /** True for the format the master already is: served with no conversion. */
  is_source: boolean;
  encoder: string;
}

export interface DownloadOptions {
  generation_id: string;
  source: { format: string | null; extension: string; bytes: number };
  default_filename: string;
  ffmpeg: { path: string | null; present: boolean };
  formats: DownloadFormat[];
}

export interface ParameterOption {
  value: string;
  label: string;
  help?: string;
  enabled?: boolean;
  disabled_reason?: string;
  capability?: string;
  /** Model options only. */
  bytes?: number | null;
  path?: string | null;
  is_default?: boolean;
  role?: string;
}

/**
 * Plain-language help served with every parameter. Only fields that are true
 * for that parameter are present, so a missing key means "nothing useful to
 * say", not "not written yet".
 */
export interface ParameterGuidance {
  severity: "info" | "caution";
  what: string;
  more?: string;
  less?: string;
  recommended?: string;
  extremes?: string;
  cost?: string;
}

export interface ParameterDefinition {
  key: string;
  label: string;
  group: string;
  type: "string" | "text" | "float" | "int" | "bool" | "enum" | "abc" | "upload";
  kind: "model" | "workflow" | "post" | "app";
  advanced: boolean;
  required?: boolean;
  readonly?: boolean;
  help?: string;
  rows?: number;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  default: unknown;
  options?: ParameterOption[];
  enabled: boolean;
  disabled_reason?: string;
  native: { supported: boolean; path: string | null; note?: string | null };
  comfy: { node: string | null; widget: string | null; note?: string | null };
  guidance?: ParameterGuidance;
  requires_mode?: string[];
  capability?: string;
  dynamic_options?: string;
}

export interface GenerationSchema {
  schema_version: number;
  registry_version: string;
  groups: { key: string; label: string; order: number; advanced: boolean; description: string }[];
  parameters: ParameterDefinition[];
  backend?: string;
  capabilities: Record<string, { supported: boolean; reason?: string; note?: string }>;
}

export interface ModelEntry {
  id: string;
  role: string;
  label: string;
  path: string | null;
  present: boolean;
  is_local: boolean;
  is_default: boolean;
  bytes: number | null;
  problem: string | null;
}

export interface Capabilities {
  label: string;
  backend: string;
  modes: GenerationMode[];
  capabilities: Record<string, { supported: boolean; reason?: string; note?: string }>;
  models: ModelEntry[];
  probe: Record<string, unknown>;
}

export interface GpuDevice {
  index: number;
  name: string;
  memory_total_bytes: number;
  memory_used_bytes: number;
  memory_free_bytes: number;
  compute_capability: string | null;
  bf16_supported: boolean | null;
  utilisation_percent: number | null;
  temperature_c: number | null;
  other_process_count: number;
  other_process_bytes: number;
  selected: boolean;
  reported_by: "worker" | "nvml";
  live_stats?: boolean;
}

export interface GpuInventory {
  devices: GpuDevice[];
  selected_index: number;
  active_index: number | null;
  pending_restart: boolean;
  worker_online: boolean;
  driver_version: string | null;
  error: string | null;
  cuda_visible_devices: string | null;
  note: string | null;
}

export type Risk = "SAFE" | "WARNING" | "UNSAFE";

/** Token accounting for one request, served by /api/v1/generation/estimate. */
export interface BudgetEstimate {
  stage: "request" | "plan";
  risk: Risk;
  exact_tokenisation: boolean;
  tokenisation_note: string | null;
  context_tokens: number;
  input_context_tokens: number;
  prefix_breakdown: {
    document: number;
    instruction_style_lyrics: number;
    markers: number;
    score: number;
  };
  plan_reserve_tokens: number;
  reserved_tokens: number;
  safety_margin_tokens: number;
  available_generation_tokens: number;
  requested_tokens: number;
  requested_seconds: number;
  max_safe_tokens: number;
  max_safe_seconds: number;
  planned_seconds: number | null;
  planned_tokens: number | null;
  kv_cache_bytes: number;
  cfg_branches: number;
  supports_continuation: boolean;
  supports_chunked_generation: boolean;
  reasons: string[];
  remedies: string[];
  excess_tokens: number;
  effective_tokens?: number;
  effective_seconds?: number;
}

export interface ModelLimits {
  model_id: string;
  protocol: string;
  context_tokens: number;
  latent_frame_rate: number;
  reserved_tokens: number;
  safety_margin_tokens: number;
  warning_threshold: number;
  plan_length_tolerance: number;
  supports_continuation: boolean;
  supports_chunked_generation: boolean;
  capability_note: string;
  kv_cache_bytes_per_token: number;
  sources: Record<string, string>;
}

export interface BudgetResponse {
  estimate: BudgetEstimate;
  limits: ModelLimits;
}

export interface DeleteReport {
  deleted: boolean;
  generation_id: string;
  artifacts_removed: number;
  complete: boolean;
  failures: { path: string; error: string }[];
}

export interface QueueView {
  active: {
    id: string;
    title: string;
    status: JobStatus;
    progress: ProgressState;
    elapsed_seconds: number;
    worker_id: string | null;
    priority: number;
  }[];
  queued: { id: string; title: string; queue_position: number | null; priority: number; waiting_seconds: number }[];
  depth: number;
  max_concurrent_gpu_jobs: number;
}

export interface SystemInfo {
  app: Record<string, unknown>;
  gpus: {
    index: number;
    name: string;
    memory_total_bytes: number;
    memory_used_bytes: number;
    memory_free_bytes: number;
    compute_capability: string;
    utilisation_percent: number | null;
    temperature_c: number | null;
  }[];
  driver_version: string | null;
  gpu_error: string | null;
  disk: { total_bytes: number; used_bytes: number; free_bytes: number; path: string };
  queue: { depth: number; active: unknown[]; by_status: Record<string, number>; total_generations: number };
  worker: { workers: WorkerHeartbeat[]; online: boolean };
  devices: GpuInventory;
  models: Record<string, unknown>;
}

export interface WorkerHeartbeat {
  worker_id: string;
  state: string;
  backend: string;
  updated_at: string;
  current_generation_id: string | null;
  model: Record<string, unknown>;
  runtime: Record<string, unknown>;
  gpu: Record<string, unknown>;
  online: boolean;
  stale: boolean;
}

export interface Preset {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  config: GenerationConfig;
}

export interface ScoreBundle {
  score: {
    id: string;
    generation_id: string;
    project_id: string;
    source_abc: string;
    edited_abc: string | null;
    origin: string;
    warnings: string[];
  };
  source: { valid: boolean | null; report: unknown; error: string | null };
  edited: { valid: boolean | null; report: unknown; error: string | null };
}

export interface ApiError {
  error_code: string;
  error_message: string;
  guidance?: string;
  stage?: string | null;
  details?: Record<string, unknown>;
}
