"use client";

import * as React from "react";

import { DownloadDialog } from "@/components/library/download-dialog";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/field";
import { useGenerationActions } from "@/hooks/use-queries";
import { ApiRequestError } from "@/lib/api";
import { useGenerationTarget } from "@/store/generation-target";

const MAX_TITLE = 120;

/**
 * Renaming one take.
 *
 * This is the metadata edit, kept deliberately separate from editing the
 * settings: a title is a label on a finished recording, while a settings
 * change produces a new version rather than altering this one.
 */
function RenameGenerationDialog() {
  const { job, action, clear } = useGenerationTarget();
  const { rename } = useGenerationActions();
  const open = action === "rename" && job !== null;

  const [title, setTitle] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (job && action === "rename") {
      setTitle(job.title);
      setError(null);
    }
  }, [job, action]);

  const trimmed = title.trim();
  const problem =
    trimmed.length === 0
      ? "A version needs a name."
      : trimmed.length > MAX_TITLE
        ? `Use at most ${MAX_TITLE} characters.`
        : null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!job || problem) return;
    setBusy(true);
    setError(null);
    try {
      await rename.mutateAsync({ id: job.id, title: trimmed });
      clear();
    } catch (renameError) {
      setError(
        renameError instanceof ApiRequestError ? renameError.message : "This version could not be renamed.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !busy) clear();
      }}
      title="Rename version"
      description="Changes the name only. The audio and the settings this version ran with stay exactly as they are."
    >
      <form onSubmit={submit} className="space-y-4">
        <Field
          label="Name"
          htmlFor="generation-name"
          required
          error={trimmed.length > MAX_TITLE ? problem : null}
          value={`${trimmed.length}/${MAX_TITLE}`}
        >
          <Input
            id="generation-name"
            autoFocus
            value={title}
            maxLength={MAX_TITLE + 40}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        {error ? <p className="text-xs text-[var(--color-danger)]">{error}</p> : null}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="surface" size="sm" onClick={clear} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={Boolean(problem)} loading={busy}>
            Save name
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** Every generation dialog that is shared across pages, mounted once. */
export function GenerationDialogHost() {
  return (
    <>
      <RenameGenerationDialog />
      <DownloadDialog />
    </>
  );
}
