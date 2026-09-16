import type {
  BudgetResponse,
  Capabilities,
  DeleteReport,
  DownloadOptions,
  GenerationJob,
  GpuInventory,
  GenerationSchema,
  Preset,
  ProjectConfigResponse,
  ProjectDeleteReport,
  ProjectSummary,
  QueueView,
  ScoreBundle,
  SongProject,
  SystemInfo,
} from "@/types/api";

/** Same-origin in the browser (Next rewrites proxy to FastAPI); absolute on the server. */
const BASE =
  typeof window === "undefined"
    ? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
    : "";

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly guidance?: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let payload: Record<string, unknown> = {};
    try {
      payload = await response.json();
    } catch {
      /* the body was not JSON; fall through to the status text */
    }
    throw new ApiRequestError(
      (payload.error_message as string) ?? response.statusText,
      response.status,
      (payload.error_code as string) ?? "UNKNOWN",
      payload.guidance as string | undefined,
      payload.details as Record<string, unknown> | undefined,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; ready: boolean; worker_online: boolean; backend: string }>("/api/v1/health"),
  systemInfo: () => request<SystemInfo>("/api/v1/system/info"),
  gpus: () => request<GpuInventory>("/api/v1/system/gpus"),
  selectDevice: (deviceIndex: number) =>
    request<GpuInventory>("/api/v1/system/device", {
      method: "PUT",
      body: JSON.stringify({ device_index: deviceIndex }),
    }),
  vramEstimate: (seconds: number, decoderMode: string, budget: number) =>
    request<{ warning: { message: string; estimate_gib: number; available_gib: number } | null }>(
      `/api/v1/system/vram-estimate?seconds=${seconds}&decoder_mode=${decoderMode}&budget_gib=${budget}`,
    ),

  schema: () => request<GenerationSchema>("/api/v1/generation/schema"),
  estimateBudget: (config: Record<string, unknown>) =>
    request<BudgetResponse>("/api/v1/generation/estimate", {
      method: "POST",
      body: JSON.stringify({ config }),
    }),
  capabilities: () => request<Capabilities>("/api/v1/models/capabilities"),
  workflowMapping: () => request<Record<string, unknown>>("/api/v1/generation/workflow-mapping"),

  presets: () => request<{ items: Preset[]; defaults: Record<string, unknown> }>("/api/v1/presets"),
  createPreset: (body: { name: string; description?: string; config: Record<string, unknown> }) =>
    request<Preset>("/api/v1/presets", { method: "POST", body: JSON.stringify(body) }),
  deletePreset: (id: string) => request<void>(`/api/v1/presets/${id}`, { method: "DELETE" }),

  projects: () => request<{ items: ProjectSummary[] }>("/api/v1/projects"),
  project: (id: string) =>
    request<{ project: SongProject; generations: GenerationJob[] }>(`/api/v1/projects/${id}`),
  updateProject: (id: string, body: Record<string, unknown>) =>
    request<SongProject>(`/api/v1/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  projectConfig: (id: string) => request<ProjectConfigResponse>(`/api/v1/projects/${id}/config`),
  saveProjectConfig: (id: string, config: Record<string, unknown>) =>
    request<SongProject>(`/api/v1/projects/${id}/config`, {
      method: "PUT",
      body: JSON.stringify({ config }),
    }),
  deleteProject: (id: string) =>
    request<ProjectDeleteReport>(`/api/v1/projects/${id}`, { method: "DELETE" }),

  createGeneration: (body: {
    project_id?: string | null;
    parent_generation_id?: string | null;
    title?: string;
    tags?: string[];
    priority?: number;
    config: Record<string, unknown>;
  }) =>
    request<{ generation: GenerationJob; project: SongProject; warnings: string[] }>("/api/v1/generations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  generations: (params: Record<string, string | number | boolean | undefined>) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "" && value !== null) search.append(key, String(value));
    });
    return request<{ total: number; limit: number; offset: number; items: GenerationJob[] }>(
      `/api/v1/generations?${search.toString()}`,
    );
  },
  generation: (id: string) =>
    request<{ generation: GenerationJob; project: SongProject }>(`/api/v1/generations/${id}`),
  patchGeneration: (id: string, body: { title?: string; favorite?: boolean }) =>
    request<GenerationJob>(`/api/v1/generations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteGeneration: (id: string) =>
    request<DeleteReport>(`/api/v1/generations/${id}`, { method: "DELETE" }),
  cancelGeneration: (id: string) => request<GenerationJob>(`/api/v1/generations/${id}/cancel`, { method: "POST" }),
  retryGeneration: (id: string) => request<GenerationJob>(`/api/v1/generations/${id}/retry`, { method: "POST" }),
  duplicateGeneration: (id: string, overrides: Record<string, unknown> = {}) =>
    request<GenerationJob>(`/api/v1/generations/${id}/duplicate`, {
      method: "POST",
      body: JSON.stringify(overrides),
    }),
  manifest: (id: string) => request<Record<string, unknown>>(`/api/v1/generations/${id}/manifest`),
  log: (id: string) =>
    request<{ items: { timestamp: string; severity: string; stage: string; message: string }[] }>(
      `/api/v1/generations/${id}/log`,
    ),
  queue: () => request<QueueView>("/api/v1/queue"),

  score: (id: string) => request<ScoreBundle>(`/api/v1/scores/${id}`),
  saveScore: (id: string, editedAbc: string) =>
    request<{ score: ScoreBundle["score"]; comparison: Record<string, unknown> | null }>(`/api/v1/scores/${id}`, {
      method: "PUT",
      body: JSON.stringify({ edited_abc: editedAbc }),
    }),
  validateAbc: (abc: string) =>
    request<{ valid: boolean; report: unknown; error: string | null }>("/api/v1/scores/validate", {
      method: "POST",
      body: JSON.stringify({ abc }),
    }),
  compareScore: (id: string, after: string, before?: string) =>
    request<Record<string, unknown>>(`/api/v1/scores/${id}/compare`, {
      method: "POST",
      body: JSON.stringify({ after, before }),
    }),
  regenerateFromScore: (id: string, overrides: Record<string, unknown> = {}) =>
    request<GenerationJob>(`/api/v1/scores/${id}/regenerate`, {
      method: "POST",
      body: JSON.stringify(overrides),
    }),

  uploadAudio: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ upload: { id: string; filename: string; duration_seconds: number | null }; probe: Record<string, unknown> }>(
      "/api/v1/uploads",
      { method: "POST", body: form },
    );
  },

  downloadOptions: (id: string) => request<DownloadOptions>(`/api/v1/artifacts/${id}/formats`),

  audioUrl: (id: string) => `${BASE}/api/v1/artifacts/${id}/audio`,
  /**
   * Download link. Conversion happens on the backend, which is also where the
   * filename is sanitised: the query string is a request, not a guarantee.
   */
  downloadUrl: (id: string, options?: { format?: string; filename?: string }) => {
    const search = new URLSearchParams();
    if (options?.format) search.set("format", options.format);
    if (options?.filename) search.set("filename", options.filename);
    const query = search.toString();
    return `${BASE}/api/v1/artifacts/${id}/download${query ? `?${query}` : ""}`;
  },
  eventsUrl: (id: string) => `${BASE}/api/v1/generations/${id}/events`,
};
