"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/field";
import { useProjectActions } from "@/hooks/use-queries";
import { ApiRequestError } from "@/lib/api";
import { useProjectTarget } from "@/store/project-target";

const MAX_TITLE = 120;

/**
 * The application's rename and delete dialogs for projects.
 *
 * Mounted once in the app shell. Cards ask for a dialog through the store
 * rather than rendering their own, because deleting a project unmounts the
 * card that started it — and an overlay unmounting while open leaves the
 * document body with `pointer-events: none`, which makes the whole page stop
 * responding to clicks until the next full render.
 */
export function ProjectDialogHost() {
  const router = useRouter();
  const { project, action, redirectTo, clear } = useProjectTarget();
  const { rename, remove } = useProjectActions();

  // Keep the last target while the dialog animates closed, so its text does
  // not blank out mid-close.
  const [shown, setShown] = React.useState(project);
  const [title, setTitle] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (project) {
      setShown(project);
      setTitle(project.title);
      setError(null);
    }
  }, [project]);

  const close = () => {
    if (busy) return;
    clear();
  };

  const trimmed = title.trim();
  const nameProblem =
    trimmed.length === 0
      ? "A project needs a name."
      : trimmed.length > MAX_TITLE
        ? `Use at most ${MAX_TITLE} characters.`
        : null;

  const submitRename = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!project || nameProblem) return;
    setBusy(true);
    setError(null);
    try {
      await rename.mutateAsync({ id: project.id, title: trimmed });
      clear();
    } catch (renameError) {
      setError(
        renameError instanceof ApiRequestError ? renameError.message : "The project could not be renamed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      const report = await remove.mutateAsync(project.id);
      if (!report.complete) {
        setError(
          `Removed ${report.generations_removed} generation(s), but ${report.failures.length} file(s) ` +
            "could not be deleted. Check permissions on the data directory.",
        );
        return;
      }
      // Close before navigating: the overlay has to finish unmounting while
      // this host is still on screen.
      clear();
      if (redirectTo) router.push(redirectTo);
    } catch (deleteError) {
      setError(
        deleteError instanceof ApiRequestError ? deleteError.message : "The project could not be deleted.",
      );
    } finally {
      setBusy(false);
    }
  };

  const takes = shown && "generation_count" in shown ? shown.generation_count : null;

  return (
    <>
      <Dialog
        open={action === "rename"}
        onOpenChange={(next) => {
          if (!next) close();
        }}
        title="Rename project"
        description="This changes the project's name only. Its generations and their settings are untouched."
      >
        <form onSubmit={submitRename} className="space-y-4">
          <Field
            label="Project name"
            htmlFor="project-name"
            required
            error={trimmed.length > MAX_TITLE ? nameProblem : null}
            value={`${trimmed.length}/${MAX_TITLE}`}
          >
            <Input
              id="project-name"
              autoFocus
              value={title}
              maxLength={MAX_TITLE + 40}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>
          {error ? <p className="text-xs text-[var(--color-danger)]">{error}</p> : null}
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="surface" size="sm" onClick={close} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" size="sm" disabled={Boolean(nameProblem)} loading={busy}>
              Save name
            </Button>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog
        open={action === "delete"}
        onOpenChange={(next) => {
          if (!next) close();
        }}
        title={`Delete “${shown?.title || "Untitled project"}”?`}
        description="This permanently removes the project and its whole generation history. It cannot be undone."
        busy={busy}
        confirmLabel="Delete project"
        onConfirm={confirmDelete}
        details={
          <div className="space-y-2">
            <ul className="space-y-1 text-sm">
              <li>
                •{" "}
                {takes === null
                  ? "every generation in this project"
                  : `${takes} generation${takes === 1 ? "" : "s"} in this project`}
              </li>
              <li>• the audio, scores, latents, logs and manifests belonging to them</li>
              <li>• the project record and its saved settings</li>
            </ul>
            <p className="text-xs text-[var(--color-ink-faint)]">
              Other projects, your uploads and the model files are not affected. A project with a
              generation still running cannot be deleted; cancel it first.
            </p>
            {error ? <p className="text-xs text-[var(--color-danger)]">{error}</p> : null}
          </div>
        }
      />
    </>
  );
}
