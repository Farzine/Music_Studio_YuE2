"use client";

import { AudioLines, Loader2, Play, Trash2, TriangleAlert, Upload } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiRequestError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatBytes, formatDuration } from "@/lib/format";

export interface UploadedAudio {
  id: string;
  filename: string;
  bytes: number;
  durationSeconds: number | null;
  sampleRate: number | null;
  channels: number | null;
  probeError?: string;
}

const ACCEPTED = [".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aiff", ".aif"];
const MAX_BYTES = 100 * 1024 * 1024;

/**
 * Reference-audio upload for the cover workflow.
 *
 * Validates type, size and readability in the browser for a fast answer; the
 * backend checks all of it again independently, because a browser check is a
 * convenience and not a guarantee.
 */
export function AudioUploader({
  value,
  onChange,
  disabled,
  disabledReason,
}: {
  value: UploadedAudio | null;
  onChange: (value: UploadedAudio | null) => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const [dragging, setDragging] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const upload = async (file: File) => {
    setError(null);
    const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
    if (!ACCEPTED.includes(extension)) {
      setError(`${extension || "That file type"} is not supported. Use ${ACCEPTED.join(", ")}.`);
      return;
    }
    if (file.size > MAX_BYTES) {
      setError(`The file is ${formatBytes(file.size)}; the limit is ${formatBytes(MAX_BYTES)}.`);
      return;
    }
    if (file.size === 0) {
      setError("That file is empty.");
      return;
    }

    setBusy(true);
    try {
      const result = await api.uploadAudio(file);
      const probe = result.probe as { probe_error?: string; sample_rate?: number; channels?: number };
      onChange({
        id: result.upload.id,
        filename: result.upload.filename,
        bytes: file.size,
        durationSeconds: result.upload.duration_seconds,
        sampleRate: probe.sample_rate ?? null,
        channels: probe.channels ?? null,
        probeError: probe.probe_error,
      });
    } catch (uploadError) {
      setError(
        uploadError instanceof ApiRequestError
          ? uploadError.message
          : "The upload failed. Check that the API is running.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (disabled) {
    return (
      <div className="rounded-[var(--radius-md)] border border-[var(--color-warn-soft)] bg-[var(--color-warn-soft)] p-4">
        <p className="flex items-center gap-2 text-sm font-medium text-[var(--color-warn)]">
          <TriangleAlert className="h-4 w-4" />
          Cover is not available
        </p>
        <p className="mt-1 text-sm leading-relaxed text-[var(--color-ink-muted)]">
          {disabledReason ?? "The active backend does not advertise the cover capability."}
        </p>
      </div>
    );
  }

  if (value) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-3">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[var(--radius-sm)] bg-[var(--color-surface-2)]">
            <AudioLines className="h-5 w-5 text-[var(--color-accent)]" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{value.filename}</p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {value.durationSeconds != null ? (
                <Badge tone="outline">{formatDuration(value.durationSeconds)}</Badge>
              ) : null}
              {value.sampleRate ? <Badge tone="outline">{(value.sampleRate / 1000).toFixed(1)} kHz</Badge> : null}
              {value.channels ? (
                <Badge tone="outline">{value.channels === 2 ? "stereo" : "mono"}</Badge>
              ) : null}
              <Badge tone="outline">{formatBytes(value.bytes)}</Badge>
            </div>
          </div>
          <Button variant="ghost" size="icon" asChild aria-label="Preview reference audio">
            <a href={`/api/v1/uploads/${value.id}/audio`} target="_blank" rel="noreferrer">
              <Play className="h-4 w-4" />
            </a>
          </Button>
          <Button variant="ghost" size="icon" aria-label="Remove reference audio" onClick={() => onChange(null)}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
        {value.probeError ? (
          <p className="text-xs text-[var(--color-warn)]">
            The duration could not be read locally, so it will be measured during transcription.
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void upload(file);
        }}
        className={cn(
          "flex flex-col items-center gap-2.5 rounded-[var(--radius-md)] border border-dashed p-6 text-center transition-colors",
          dragging
            ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
            : "border-[var(--color-line)]",
        )}
      >
        {busy ? (
          <Loader2 className="h-5 w-5 animate-spin text-[var(--color-accent)]" />
        ) : (
          <Upload className="h-5 w-5 text-[var(--color-ink-faint)]" />
        )}
        <p className="text-sm">{busy ? "Uploading…" : "Drop an audio file here"}</p>
        <p className="text-xs text-[var(--color-ink-faint)]">
          {ACCEPTED.join(", ")} · up to {formatBytes(MAX_BYTES)}
        </p>
        <Button variant="surface" size="sm" onClick={() => inputRef.current?.click()} disabled={busy}>
          Choose a file
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(",")}
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
            event.target.value = "";
          }}
        />
      </div>
      <p className="text-xs leading-relaxed text-[var(--color-ink-faint)]">
        The recording is transcribed into a melody score, which then guides generation in your chosen style.
        Transcription is an estimate, not an exact copy — review the score on the result page.
      </p>
      {error ? <p className="text-xs text-[var(--color-danger)]">{error}</p> : null}
    </div>
  );
}
