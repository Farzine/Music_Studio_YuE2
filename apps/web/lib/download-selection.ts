import type { ModelDownloadMode } from "../types/api";

/** UI request identity: a preview is usable only for the unchanged selection. */
export function downloadSelectionKey(repo: string, revision: string, filename: string, mode: ModelDownloadMode,
  selectedFiles: string[], deviceIndex?: number) {
  return JSON.stringify([repo.trim(), revision.trim(), filename.trim(), mode, [...selectedFiles].sort(), deviceIndex ?? null]);
}
