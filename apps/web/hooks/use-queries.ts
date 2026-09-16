"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { GenerationJob } from "@/types/api";

const ACTIVE = new Set([
  "QUEUED",
  "LOADING_MODEL",
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
  useQuery({ queryKey: keys.project(id ?? ""), queryFn: () => api.project(id as string), enabled: Boolean(id) });
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
