"use client";

import * as React from "react";

import { ConfirmDialog } from "@/components/ui/dialog";
import { ApiRequestError } from "@/lib/api";
import type { DeleteReport, GenerationJob } from "@/types/api";

/**
 * Confirmation for deleting a generation.
 *
 * Deletion is irreversible, so it lists exactly what will be removed and
 * requires a deliberate second action. If the backend reports that some files
 * survived, that is shown rather than treated as success.
 */
export function DeleteGenerationDialog({
  job,
  open,
  onOpenChange,
  onDelete,
  onDeleted,
}: {
  job: GenerationJob | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDelete: (id: string) => Promise<DeleteReport>;
  onDeleted?: (report: DeleteReport) => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) setError(null);
  }, [open]);

  if (!job) return null;

  const hasAudio = job.artifacts.some((artifact) => artifact.kind === "audio");
  const hasScore = job.artifacts.some((artifact) => artifact.kind === "score");

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const report = await onDelete(job.id);
      if (!report.complete) {
        setError(
          `Removed ${report.artifacts_removed} files, but ${report.failures.length} could not be deleted. ` +
            `Check permissions on the data directory.`,
        );
        setBusy(false);
        return;
      }
      onDeleted?.(report);
      onOpenChange(false);
    } catch (deleteError) {
      setError(
        deleteError instanceof ApiRequestError ? deleteError.message : "The generation could not be deleted.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete “${job.title || "Untitled"}”?`}
      description="This permanently removes the generation and everything belonging to it. It cannot be undone."
      busy={busy}
      confirmLabel="Delete permanently"
      onConfirm={confirm}
      details={
        <div className="space-y-2">
          <ul className="space-y-1 text-sm">
            {hasAudio ? <li>• the generated audio</li> : null}
            <li>• the generation record and its settings</li>
            {hasScore ? <li>• the score and any edits you made to it</li> : null}
            <li>• saved latents, logs and the manifest</li>
          </ul>
          <p className="text-xs text-[var(--color-ink-faint)]">
            Other generations, your projects and the model files are not affected.
          </p>
          {error ? <p className="text-xs text-[var(--color-danger)]">{error}</p> : null}
        </div>
      }
    />
  );
}
