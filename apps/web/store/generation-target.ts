"use client";

import { create } from "zustand";

import type { GenerationJob } from "@/types/api";

export type GenerationAction = "rename" | "download";

interface GenerationTargetState {
  job: GenerationJob | null;
  action: GenerationAction | null;
  request: (action: GenerationAction, job: GenerationJob) => void;
  clear: () => void;
}

/**
 * The generation a rename or download dialog is currently about.
 *
 * Held in a store for the same reason as the delete target: these dialogs are
 * mounted once at the top of the tree rather than inside each card. A dialog
 * that unmounts while still open leaves `pointer-events: none` on the document
 * body, and the page then ignores every click until the next full render.
 */
export const useGenerationTarget = create<GenerationTargetState>((set) => ({
  job: null,
  action: null,
  request: (action, job) => set({ action, job }),
  clear: () => set({ job: null, action: null }),
}));
