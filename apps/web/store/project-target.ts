"use client";

import { create } from "zustand";

import type { ProjectSummary, SongProject } from "@/types/api";

export type ProjectAction = "rename" | "delete";

interface ProjectTargetState {
  project: SongProject | ProjectSummary | null;
  action: ProjectAction | null;
  /** Where to go once a deletion succeeds, when the page shows that project. */
  redirectTo: string | null;
  request: (
    action: ProjectAction,
    project: SongProject | ProjectSummary,
    options?: { redirectTo?: string },
  ) => void;
  clear: () => void;
}

/**
 * The project a rename or delete dialog is currently about.
 *
 * Both dialogs live once in the app shell rather than inside the card that
 * opened them, because deleting a project unmounts that card — and an overlay
 * that unmounts while open leaves the document body unclickable.
 */
export const useProjectTarget = create<ProjectTargetState>((set) => ({
  project: null,
  action: null,
  redirectTo: null,
  request: (action, project, options) =>
    set({ action, project, redirectTo: options?.redirectTo ?? null }),
  clear: () => set({ project: null, action: null, redirectTo: null }),
}));
