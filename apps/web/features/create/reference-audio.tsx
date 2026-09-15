"use client";

import { AudioLines, Trash2, Upload } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { WarningNotice } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";

export interface ReferenceAudio {
  id: string;
  filename: string;
  durationSeconds: number | null;
  probeError?: string;
}

/**
 * Reference audio for the cover workflow.
 *
 * Disabled unless the backend advertises the cover capability; the reason it
 * gives is shown rather than a generic message, and transcription is never
 * described as exact.
 */
export function ReferenceAudioPanel({
  enabled,
  disabledReason,
  value,
  onChange,
}: {
  enabled: boolean;
  disabledReason?: string;
  value: ReferenceAudio | null;
  onChange: (value: ReferenceAudio | null) => void;
}) {
  const [dragging, setDragging] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.uploadAudio(file);
      onChange({
        id: result.upload.id,
        filename: result.upload.filename,
        durationSeconds: result.upload.duration_seconds,
        probeError: (result.probe as { probe_error?: string }).probe_error,
      });
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  if (!enabled) {
    return (
      <WarningNotice>
        <p className="font-medium">Cover workflow unavailable</p>
        <p className="mt-1 text-[var(--color-ink-muted)]">
          {disabledReason ?? "The active backend does not advertise the cover capability."}
        </p>
      </WarningNotice>
    );
  }

  if (value) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-[var(--color-line)] bg-[var(--color-canvas)] p-3">
        <span className="grid h-10 w-10 place-items-center rounded-lg bg-[var(--color-surface-2)]">
          <AudioLines className="h-4 w-4 text-[var(--color-accent)]" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm">{value.filename}</p>
          <p className="text-xs text-[var(--color-ink-faint)]">
            {value.durationSeconds != null
              ? formatDuration(value.durationSeconds)
              : value.probeError
                ? "Duration unknown (the file could not be probed locally)"
                : "Duration unknown"}
          </p>
        </div>
        <Button variant="ghost" size="icon" aria-label="Remove reference audio" onClick={() => onChange(null)}>
          <Trash2 className="h-4 w-4" />
        </Button>
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
          "flex flex-col items-center gap-2 rounded-xl border border-dashed p-6 text-center transition-colors",
          dragging ? "border-[var(--color-accent)] bg-[color-mix(in_oklch,var(--color-accent)_8%,transparent)]" : "border-[var(--color-line)]",
        )}
      >
        <Upload className="h-5 w-5 text-[var(--color-ink-faint)]" />
        <p className="text-sm">{busy ? "Uploading…" : "Drop an audio file here"}</p>
        <p className="text-xs text-[var(--color-ink-faint)]">WAV, FLAC, MP3, OGG, M4A or AIFF</p>
        <Button variant="surface" size="sm" onClick={() => inputRef.current?.click()} disabled={busy}>
          Choose a file
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept="audio/*"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
          }}
        />
      </div>
      <p className="text-xs text-[var(--color-ink-faint)]">
        The reference is transcribed to a melody score before generation. Transcription is not guaranteed to be
        exact — review the score before you regenerate from it.
      </p>
      {error ? <p className="text-xs text-[var(--color-danger)]">{error}</p> : null}
    </div>
  );
}
