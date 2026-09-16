"use client";

import { create } from "zustand";

import type { GenerationJob } from "@/types/api";

interface DeleteTargetState {
  job: GenerationJob | null;
  /** Where to go once the deletion succeeds, when the current page shows it. */
  redirectTo: string | null;
  request: (job: GenerationJob, options?: { redirectTo?: string }) => void;
  clear: () => void;
}

/**
 * The generation awaiting delete confirmation.
 *
 * Kept in a store rather than in each card so the confirmation dialog can live
 * at the top of the tree. A dialog rendered inside the card would unmount at
 * the exact moment the deletion removes that card from the list, and an
 * overlay that unmounts while still open leaves `pointer-events: none` on the
 * document body — the page then looks fine but ignores every click.
 */
export const useDeleteTarget = create<DeleteTargetState>((set) => ({
  job: null,
  redirectTo: null,
  request: (job, options) => set({ job, redirectTo: options?.redirectTo ?? null }),
  clear: () => set({ job: null, redirectTo: null }),
}));
