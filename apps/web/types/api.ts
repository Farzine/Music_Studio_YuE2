/** Shapes served by the FastAPI backend. Mirrors packages/core models. */

export type JobStatus =
  | "DRAFT"
  | "QUEUED"
  | "LOADING_MODEL"
  | "PLANNING"
  | "GENERATING"
  | "DECODING"
  | "POST_PROCESSING"
  | "COMPLETED"
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
  prompt: { style: string; lyrics: string; abc: string; mode: GenerationMode };
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
  favorite: boolean;
  created_at: string;
  updated_at: string;
}

export interface ParameterOption {
  value: string;
  label: string;
  help?: string;
  enabled?: boolean;
  disabled_reason?: string;
  capability?: string;
}

export interface ParameterDefinition {
  key: string;
  label: string;
  group: string;
  type: "string" | "text" | "float" | "int" | "bool" | "enum" | "abc";
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
}

export interface GenerationSchema {
  schema_version: number;
  registry_version: string;
  groups: { key: string; label: string; order: number; advanced: boolean; description: string }[];
  parameters: ParameterDefinition[];
  backend?: string;
  capabilities: Record<string, { supported: boolean; reason?: string; note?: string }>;
}

export interface Capabilities {
  label: string;
  backend: string;
  modes: GenerationMode[];
  capabilities: Record<string, { supported: boolean; reason?: string; note?: string }>;
  models: { id: string; role: string; label: string; present: boolean; bytes: number | null }[];
  probe: Record<string, unknown>;
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
