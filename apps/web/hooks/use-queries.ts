"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { GenerationJob } from "@/types/api";

const ACTIVE = new Set([
  "QUEUED",
  "LOADING_MODEL",
  "TRANSCRIBING",
  "PLANNING",
  "GENERATING",
  "DECODING",
  "POST_PROCESSING",
  "CANCEL_REQUESTED",
]);

export const keys = {
  schema: ["schema"] as const,
  capabilities: ["capabilities"] as const,
  presets: ["presets"] as const,
  health: ["health"] as const,
  system: ["system"] as const,
  gpus: ["gpus"] as const,
  queue: ["queue"] as const,
  generations: (params: Record<string, unknown>) => ["generations", params] as const,
  generation: (id: string) => ["generation", id] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  projectConfig: (id: string) => ["project-config", id] as const,
  downloadOptions: (id: string) => ["download-options", id] as const,
  score: (id: string) => ["score", id] as const,
  manifest: (id: string) => ["manifest", id] as const,
  log: (id: string) => ["log", id] as const,
};

export const useSchema = () => useQuery({ queryKey: keys.schema, queryFn: api.schema, staleTime: 60_000 });
export const useCapabilities = () =>
  useQuery({ queryKey: keys.capabilities, queryFn: api.capabilities, staleTime: 30_000 });
export const usePresets = () => useQuery({ queryKey: keys.presets, queryFn: api.presets, staleTime: 60_000 });
export const useHealth = () =>
  useQuery({ queryKey: keys.health, queryFn: api.health, refetchInterval: 15_000 });
export const useSystemInfo = () =>
  useQuery({ queryKey: keys.system, queryFn: api.systemInfo, refetchInterval: 5_000 });

export const useGpus = () =>
  useQuery({ queryKey: keys.gpus, queryFn: api.gpus, refetchInterval: 5_000 });

/** Choosing a GPU rewrites runtime settings; the worker picks it up next job. */
export function useSelectDevice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.selectDevice,
    onSuccess: (data) => {
      client.setQueryData(keys.gpus, data);
      client.invalidateQueries({ queryKey: keys.system });
    },
  });
}

/** The queue polls quickly while anything is running, slowly when idle. */
export function useQueue() {
  return useQuery({
    queryKey: keys.queue,
    queryFn: api.queue,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && (data.active.length > 0 || data.depth > 0) ? 1_000 : 8_000;
    },
  });
}

export function useGenerations(params: Record<string, string | number | boolean | undefined>) {
  return useQuery({
    queryKey: keys.generations(params),
    queryFn: () => api.generations(params),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((job: GenerationJob) => ACTIVE.has(job.status)) ? 2_000 : 15_000;
    },
  });
}

export function useGeneration(id: string | undefined) {
  return useQuery({
    queryKey: keys.generation(id ?? ""),
    queryFn: () => api.generation(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && ACTIVE.has(query.state.data.generation.status) ? 1_500 : false,
  });
}

export const useProjects = () => useQuery({ queryKey: keys.projects, queryFn: api.projects });
export const useProject = (id: string | undefined) =>
  useQuery({
    queryKey: keys.project(id ?? ""),
    queryFn: () => api.project(id as string),
    enabled: Boolean(id),
    // A project page is a generation history: it has to follow a running take.
    refetchInterval: (query) =>
      (query.state.data?.generations ?? []).some((job: GenerationJob) => ACTIVE.has(job.status))
        ? 2_000
        : false,
  });
export const useProjectConfig = (id: string | undefined) =>
  useQuery({
    queryKey: keys.projectConfig(id ?? ""),
    queryFn: () => api.projectConfig(id as string),
    enabled: Boolean(id),
  });

/** What the picked generation can be downloaded as, asked of the backend. */
export const useDownloadOptions = (id: string | undefined) =>
  useQuery({
    queryKey: keys.downloadOptions(id ?? ""),
    queryFn: () => api.downloadOptions(id as string),
    enabled: Boolean(id),
    staleTime: 60_000,
    retry: false,
  });

/**
 * Renaming, editing settings and deleting a project.
 *
 * Every one of these changes what the project list and the project page show,
 * so they invalidate both rather than patching a cached copy: a stale count or
 * a deleted project still on screen is worse than one extra fetch.
 */
export function useProjectActions() {
  const client = useQueryClient();
  const invalidate = (id?: string) => {
    client.invalidateQueries({ queryKey: keys.projects });
    if (id) {
      client.invalidateQueries({ queryKey: keys.project(id) });
      client.invalidateQueries({ queryKey: keys.projectConfig(id) });
    }
  };
  return {
    rename: useMutation({
      mutationFn: ({ id, title }: { id: string; title: string }) => api.updateProject(id, { title }),
      onSuccess: (project) => invalidate(project.id),
    }),
    updateConfig: useMutation({
      mutationFn: ({ id, config }: { id: string; config: Record<string, unknown> }) =>
        api.saveProjectConfig(id, config),
      onSuccess: (project) => invalidate(project.id),
    }),
    remove: useMutation({
      mutationFn: api.deleteProject,
      onSuccess: (report) => {
        invalidate(report.project_id);
        // Deleting a project removes its takes, so every generation list is stale.
        client.invalidateQueries({ queryKey: ["generations"] });
        client.invalidateQueries({ queryKey: keys.queue });
      },
    }),
  };
}
export const useScore = (id: string | undefined) =>
  useQuery({ queryKey: keys.score(id ?? ""), queryFn: () => api.score(id as string), enabled: Boolean(id), retry: false });
export const useManifest = (id: string | undefined) =>
  useQuery({ queryKey: keys.manifest(id ?? ""), queryFn: () => api.manifest(id as string), enabled: Boolean(id), retry: false });
export const useJobLog = (id: string | undefined) =>
  useQuery({ queryKey: keys.log(id ?? ""), queryFn: () => api.log(id as string), enabled: Boolean(id) });

export function useGenerationActions() {
  const client = useQueryClient();
  const invalidate = () => {
    client.invalidateQueries({ queryKey: ["generations"] });
    client.invalidateQueries({ queryKey: keys.queue });
    client.invalidateQueries({ queryKey: keys.projects });
  };
  return {
    create: useMutation({ mutationFn: api.createGeneration, onSuccess: invalidate }),
    cancel: useMutation({ mutationFn: api.cancelGeneration, onSuccess: invalidate }),
    retry: useMutation({ mutationFn: api.retryGeneration, onSuccess: invalidate }),
    duplicate: useMutation({
      mutationFn: ({ id, overrides }: { id: string; overrides?: Record<string, unknown> }) =>
        api.duplicateGeneration(id, overrides ?? {}),
      onSuccess: invalidate,
    }),
    remove: useMutation({ mutationFn: api.deleteGeneration, onSuccess: invalidate }),
    favorite: useMutation({
      mutationFn: ({ id, favorite }: { id: string; favorite: boolean }) =>
        api.patchGeneration(id, { favorite }),
      onSuccess: invalidate,
    }),
    rename: useMutation({
      mutationFn: ({ id, title }: { id: string; title: string }) => api.patchGeneration(id, { title }),
      onSuccess: invalidate,
    }),
  };
}
