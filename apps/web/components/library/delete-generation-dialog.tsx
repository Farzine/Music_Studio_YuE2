"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { ConfirmDialog } from "@/components/ui/dialog";
import { useGenerationActions } from "@/hooks/use-queries";
import { ApiRequestError } from "@/lib/api";
import { useDeleteTarget } from "@/store/delete-target";

/**
 * The application's single delete-confirmation dialog.
 *
 * Mounted once in the app shell. Cards and detail pages ask for a deletion
 * through the store instead of rendering their own dialog, because the element
 * being deleted is usually the one that would own it: when the list refreshes,
 * that card unmounts, and an open overlay that unmounts takes its
 * `pointer-events: none` body lock with it, freezing the whole page until the
 * next full render.
 *
 * Deletion is irreversible, so this states exactly what will be removed and
 * requires a deliberate second action. A partial failure reported by the
 * backend is shown rather than treated as success.
 */
export function DeleteGenerationDialogHost() {
  const router = useRouter();
  const { job, redirectTo, clear } = useDeleteTarget();
  const { remove } = useGenerationActions();
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  // The dialog element itself stays mounted across a close so Radix can run
  // its own teardown — including releasing the body pointer-events lock. The
  // last target is retained purely so the content does not blank out mid-close.
  const [shown, setShown] = React.useState(job);
  React.useEffect(() => {
    if (job) {
      setShown(job);
      setError(null);
    }
  }, [job]);

  const open = job !== null;
  const close = () => {
    if (busy) return;
    clear();
  };

  const hasAudio = shown?.artifacts.some((artifact) => artifact.kind === "audio") ?? false;
  const hasScore = shown?.artifacts.some((artifact) => artifact.kind === "score") ?? false;

  const confirm = async () => {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      const report = await remove.mutateAsync(job.id);
      if (!report.complete) {
        setError(
          `Removed ${report.artifacts_removed} files, but ${report.failures.length} could not be deleted. ` +
            "Check permissions on the data directory.",
        );
        return;
      }
      // Close first, then navigate: the overlay must finish unmounting while
      // this host is still on screen.
      clear();
      if (redirectTo) router.push(redirectTo);
    } catch (deleteError) {
      setError(
        deleteError instanceof ApiRequestError
          ? deleteError.message
          : "The generation could not be deleted.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
      title={`Delete “${shown?.title || "Untitled"}”?`}
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
