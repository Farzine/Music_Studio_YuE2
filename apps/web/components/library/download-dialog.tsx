"use client";

import { Download, FileAudio, Loader2 } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNotice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { useDownloadOptions } from "@/hooks/use-queries";
import { ApiRequestError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import { useGenerationTarget } from "@/store/generation-target";
import type { DownloadFormat } from "@/types/api";

/**
 * Mirrors the backend's filename rule closely enough to preview the result.
 *
 * The backend sanitises again and is the authority; this exists so the user
 * can see what they will get before pressing Download, not to be trusted.
 */
function previewName(typed: string, fallback: string, extension: string, known: string[]): string {
  const stripControl = (value: string) =>
    Array.from(value)
      .map((character) => {
        const code = character.codePointAt(0) ?? 0;
        if (character === "\t" || character === "\n" || character === "\r") return " ";
        return code < 32 || code === 127 ? "" : character;
      })
      .join("");

  let candidate = stripControl(typed || "")
    .replace(/\\/g, "/")
    .split("/")
    .pop() as string;
  candidate = candidate
    .replace(/[:*?"<>|]/g, "")
    .replace(/\s+/g, " ")
    .replace(/^[\s.]+|[\s.]+$/g, "");

  const dot = candidate.lastIndexOf(".");
  if (dot > 0 && known.includes(candidate.slice(dot).toLowerCase())) {
    candidate = candidate.slice(0, dot).replace(/[\s.]+$/g, "") || candidate;
  }
  if (!candidate) {
    candidate = stripControl(fallback).replace(/[:*?"<>|/\\]/g, "").trim() || "audio";
  }
  return `${candidate.slice(0, 120).replace(/[\s.]+$/g, "") || "audio"}${extension}`;
}

function FormatOption({
  format,
  checked,
  onSelect,
}: {
  format: DownloadFormat;
  checked: boolean;
  onSelect: () => void;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-[var(--radius-md)] border p-3 transition-colors",
        checked
          ? "border-[var(--color-accent)] bg-[var(--color-surface-2)]"
          : "border-[var(--color-line)] hover:border-[var(--color-line-strong)]",
      )}
    >
      <input
        type="radio"
        name="download-format"
        className="mt-1 h-4 w-4 shrink-0 accent-[var(--color-accent)]"
        checked={checked}
        onChange={onSelect}
      />
      <span className="min-w-0">
        <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
          {format.label}
          {format.is_source ? (
            <span className="rounded-[var(--radius-sm)] bg-[var(--color-surface-3)] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[var(--color-ink-muted)]">
              original
            </span>
          ) : null}
          {format.lossless ? (
            <span className="rounded-[var(--radius-sm)] bg-[var(--color-surface-3)] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[var(--color-ink-muted)]">
              lossless
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 block text-xs leading-relaxed text-[var(--color-ink-faint)]">
          {format.is_source
            ? "Handed over exactly as the model wrote it, with no conversion."
            : format.description}
        </span>
      </span>
    </label>
  );
}

/**
 * The application's single download dialog.
 *
 * The formats it lists come from the backend, which asks the installed FFmpeg
 * which encoders it actually has. A format that would fail is never offered.
 */
export function DownloadDialog() {
  const { job, action, clear } = useGenerationTarget();
  const open = action === "download" && job !== null;
  const [shown, setShown] = React.useState(job);
  const [format, setFormat] = React.useState<string | null>(null);
  const [filename, setFilename] = React.useState("");
  const [touched, setTouched] = React.useState(false);

  React.useEffect(() => {
    if (job && action === "download") {
      setShown(job);
      setFormat(null);
      setFilename("");
      setTouched(false);
    }
  }, [job, action]);

  const { data, isLoading, error } = useDownloadOptions(open ? job?.id : undefined);

  // Default to the format the file already is: no conversion, no quality lost.
  const supported = (data?.formats ?? []).filter((item) => item.supported);
  const selected = format ?? data?.source.format ?? supported[0]?.id ?? null;
  const selectedFormat = supported.find((item) => item.id === selected) ?? null;
  const extensions = (data?.formats ?? []).map((item) => item.extension);
  const fallback = data?.default_filename ?? shown?.title ?? "audio";
  const finalName = selectedFormat
    ? previewName(touched ? filename : fallback, fallback, selectedFormat.extension, extensions)
    : "";

  const unavailable = (data?.formats ?? []).filter((item) => !item.supported);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) clear();
      }}
      title="Download audio"
      description={shown ? `“${shown.title || "Untitled"}” · version ${shown.version}` : undefined}
      footer={
        <>
          <Button variant="surface" size="sm" onClick={clear}>
            Cancel
          </Button>
          {selectedFormat && job ? (
            <Button variant="primary" size="sm" asChild>
              <a
                href={api.downloadUrl(job.id, {
                  format: selectedFormat.id,
                  filename: touched ? filename : fallback,
                })}
                download={finalName}
                onClick={() => clear()}
              >
                <Download className="h-4 w-4" />
                Download
              </a>
            </Button>
          ) : (
            <Button variant="primary" size="sm" disabled>
              <Download className="h-4 w-4" />
              Download
            </Button>
          )}
        </>
      }
    >
      {isLoading ? (
        <p className="flex items-center gap-2 text-sm text-[var(--color-ink-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          Checking which formats this machine can write…
        </p>
      ) : error ? (
        <ErrorNotice
          title="Download unavailable"
          message={
            error instanceof ApiRequestError
              ? error.message
              : "The audio for this generation could not be found."
          }
        />
      ) : data ? (
        <div className="space-y-5">
          <Field label="File name" htmlFor="download-filename" description="The extension is added for you.">
            <Input
              id="download-filename"
              value={touched ? filename : fallback}
              placeholder={fallback}
              onChange={(event) => {
                setTouched(true);
                setFilename(event.target.value);
              }}
            />
          </Field>

          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium">Format</legend>
            <div className="grid gap-2">
              {supported.map((item) => (
                <FormatOption
                  key={item.id}
                  format={item}
                  checked={item.id === selected}
                  onSelect={() => setFormat(item.id)}
                />
              ))}
            </div>
          </fieldset>

          <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] px-3 py-2.5">
            <FileAudio className="h-4 w-4 shrink-0 text-[var(--color-ink-faint)]" />
            <div className="min-w-0">
              <p className="truncate font-mono text-xs">{finalName}</p>
              <p className="text-[11px] text-[var(--color-ink-faint)]">
                {selectedFormat?.is_source
                  ? `Original file, ${formatBytes(data.source.bytes)}. Nothing is re-encoded.`
                  : "Converted from the original when you press Download. The original is kept unchanged."}
              </p>
            </div>
          </div>

          {unavailable.length > 0 ? (
            <details className="text-xs text-[var(--color-ink-faint)]">
              <summary className="cursor-pointer hover:text-[var(--color-ink)]">
                {unavailable.length} format{unavailable.length === 1 ? "" : "s"} unavailable on this machine
              </summary>
              <ul className="mt-2 space-y-1">
                {unavailable.map((item) => (
                  <li key={item.id}>
                    <span className="font-medium">{item.label}</span> — {item.reason}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}
    </Dialog>
  );
}
