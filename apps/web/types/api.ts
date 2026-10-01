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
  format?: ModelEntry["format"];
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
  format: "safetensors" | "gguf" | "unknown";
  filename: string | null;
  source: "local" | "huggingface";
  huggingface_repo: string | null;
  revision: string | null;
  commit_hash: string | null;
  registry_id: string | null;
  aliases: string[];
  created_at: string | null;
  updated_at: string | null;
  architecture: string | null;
  parameter_count: number | null;
  quantization: string | null;
  precision: string | null;
  backend: string | null;
  tensor_element_count: number | null;
  checksum_sha256: string | null;
  download_status: "missing" | "downloaded" | "unknown";
  files_complete: boolean;
  validation_status: "not_validated" | "validated" | "failed";
  deletion_status: "active" | "deleting";
  registration_status: "discovered" | "registered";
  compatibility_status: "supported" | "incompatible" | "unknown";
  inference_status: "ready" | "files_missing" | "runtime_unavailable" | "incompatible" | "validation_failed" | "unknown";
  inference_ready: boolean;
  currently_loaded: boolean | null;
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
  error?: string | null;
  name: string | null;
  uuid: string | null;
  physical_index: number | null;
  pci_bus_id: string | null;
  driver_version: string | null;
  cuda_available: boolean | null;
  cuda_runtime: string | null;
  memory_total_bytes: number | null;
  memory_used_bytes: number | null;
  memory_free_bytes: number | null;
  compute_capability: string | null;
  bf16_supported: boolean | null;
  fp16_supported: boolean | null;
  fp8_supported: boolean | null;
  precision_source: string;
  memory_source: "nvml" | "worker_heartbeat";
  allocated_bytes: number | null;
  reserved_bytes: number | null;
  loaded_model: string | null;
  selectable: boolean;
  stats_updated_at: string | null;
  utilisation_percent: number | null;
  temperature_c: number | null;
  other_process_count: number | null;
  other_process_bytes: number | null;
  selected: boolean;
  reported_by: "worker" | "nvml";
  live_stats?: boolean;
}

export interface GpuInventory {
  devices: GpuDevice[];
  selected_index: number;
  active_index: number | null;
  pending_restart: boolean;
  switch_command?: {
    id: string;
    device_index: number;
    status: "queued" | "running" | "succeeded" | "failed";
    worker_online: boolean;
    progress: { stage: string; message: string } | null;
    error: { error_code: string; error_message: string; guidance?: string } | null;
  } | null;
  worker_online: boolean;
  cuda_available: boolean | null;
  driver_version: string | null;
  error: string | null;
  cuda_visible_devices: string | null;
  note: string | null;
}

export interface ModelCapacity {
  device_index: number;
  name: string | null;
  basis: string;
  free_bytes: number | null;
  available_bytes: number | null;
  reclaimable_bytes: number;
  usable_bytes: number | null;
  safety_margin_bytes: number | null;
  fixed_overhead_bytes: number;
  comfortable_model_bytes: number | null;
  conservative_model_bytes: number | null;
  upper_model_bytes: number | null;
  quantizations: { quantization: string; effective_storage_bits: number; approximate_parameters: number | null; hardware_eligible: boolean | null }[];
  reasons: string[];
}

export interface ModelAssessment {
  id: string;
  registry_id: string | null;
  label: string;
  repo_id: string | null;
  filename: string | null;
  format: string;
  backend: string | null;
  quantization: string | null;
  precision: string | null;
  architecture: string | null;
  model_bytes: number | null;
  parameters: number | null;
  device_index: number;
  status: "ready" | "recommended" | "supported" | "possibly_supported" | "not_recommended" | "cannot_run" | "unknown";
  reasons: string[];
  inference_ready: boolean;
  currently_loaded: boolean;
  runnable: boolean;
  peak_bytes: number | null;
  required_bytes: number | null;
  safe_budget_bytes: number | null;
  excess_bytes: number | null;
  vae_id: string | null;
  offload_supported: boolean;
  offload_requested: boolean;
  estimate: {
    basis: string;
    weights_bytes: number | null;
    weight_runtime_bytes: number | null;
    vae_bytes: number;
    vae_size_known: boolean;
    kv_cache_bytes: number;
    kv_source: string;
    runtime_overhead_bytes: number;
    estimated_peak_bytes: number | null;
    conservative_peak_bytes: number | null;
    estimated_system_ram_bytes: number | null;
    assumptions: string[];
  };
}

export interface ModelRecommendation {
  device_index: number;
  available_bytes: number | null;
  capacities: ModelCapacity[];
  items: ModelAssessment[];
  by_gpu: { device_index: number; items: ModelAssessment[] }[];
  variants: ModelAssessment[];
  recommended: ModelAssessment | null;
  max_model_bytes: number | null;
  max_parameters: number | null;
  memory: SystemInfo["memory"];
  scenario: { vae: string; offload_ar: boolean; compute_backend: string; memory_budget_gib: number };
  policy: Record<string, number>;
  note: string;
}

export interface HubFile {
  name: string;
  bytes: number | null;
  extension: string;
  checksum_sha256: string | null;
}

export interface HubCandidate {
  model: ModelEntry;
  required_files: string[];
  missing_files: string[];
  quantization_hint: string | null;
  metadata_basis: string;
}

export interface HubInspection {
  repo_id: string;
  requested_revision: string;
  revision: string;
  description: string | null;
  license: string | null;
  revisions: { name: string; kind: "branch" | "tag"; commit_hash: string }[];
  files: HubFile[];
  candidates: HubCandidate[];
  warnings: string[];
  device_index: number;
  assessments: ModelAssessment[];
  by_gpu: { device_index: number; items: ModelAssessment[] }[];
}

export interface HubPreview {
  repo_id: string;
  revision: string;
  filename: string;
  mode: ModelDownloadMode;
  files: HubFile[];
  total_bytes: number | null;
  known_bytes: number;
  free_bytes: number;
  destination: string;
  disk_status: "sufficient" | "insufficient" | "unknown";
  can_download: boolean;
  candidate: HubCandidate;
  assessment: ModelAssessment | null;
  warnings: string[];
}

export interface HubDiscovery {
  items: (HubInspection | { repo_id: string; error: { error_message: string } })[];
  note: string;
}

export interface ModelDownload {
  id: string;
  repo_id: string;
  filename: string;
  revision: string;
  mode?: ModelDownloadMode;
  status: "queued" | "downloading" | "verifying" | "registering" | "complete" | "failed";
  error: string | null;
  path: string | null;
  completed_files: number;
  total_files: number | null;
  current_file: string | null;
  total_bytes?: number | null;
  downloaded_bytes?: number;
  percentage?: number | null;
  current_file_bytes?: number;
  current_file_total_bytes?: number | null;
  current_file_percentage?: number | null;
  bytes_per_second?: number | null;
  eta_seconds?: number | null;
  attempt?: number;
  partial_bytes?: number | null;
  validation_status?: string;
  inference_status?: string;
}

export type ModelDownloadMode = "single" | "selected" | "repository";

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
  gpus: Partial<GpuDevice>[];
  driver_version: string | null;
  gpu_error: string | null;
  memory: {
    cpu_name: string | null;
    logical_cpu_count: number | null;
    total_bytes: number | null;
    available_bytes: number | null;
    used_bytes: number | null;
    source: string;
  };
  disk: { total_bytes: number; used_bytes: number; free_bytes: number; path: string };
  queue: { depth: number; active: unknown[]; by_status: Record<string, number>; total_generations: number };
  worker: { workers: WorkerHeartbeat[]; online: boolean };
  devices: GpuInventory;
  models: Record<string, unknown>;
}

export interface WorkerHeartbeat {
  worker_id: string;
  session_id?: string;
  current_command_id?: string | null;
  accepting_work?: boolean;
  shutdown?: { status: "running" | "completed" | "failed"; errors: { stage: string; message: string }[] } | null;
  runtime_capabilities?: { persistent_load: boolean; gguf_persistent_load: boolean; load_unload_commands: boolean; select_device_commands?: boolean; shutdown_commands?: boolean };
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
