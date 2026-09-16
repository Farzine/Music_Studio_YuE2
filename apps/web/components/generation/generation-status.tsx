"use client";

import { Check, CircleDashed, Loader2, X } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatCount } from "@/lib/format";
import type { GenerationJob, JobStatus } from "@/types/api";

/**
 * Stage-by-stage progress, from the states the backend actually reports.
 *
 * A percentage appears only where the stage has a genuine target: solver steps
 * and decoder chunks. Token stages report real counts and a rate instead,
 * because a generation limit is a ceiling rather than a target and a bar drawn
 * against it would be fiction.
 */

const ALL_STAGES: { status: JobStatus; label: string; coverOnly?: boolean }[] = [
  { status: "QUEUED", label: "Queued" },
  { status: "LOADING_MODEL", label: "Loading model" },
  { status: "TRANSCRIBING", label: "Transcribing reference", coverOnly: true },
  { status: "PLANNING", label: "Planning composition" },
  { status: "GENERATING", label: "Generating audio" },
  { status: "DECODING", label: "Decoding" },
  { status: "POST_PROCESSING", label: "Saving artifacts" },
  { status: "COMPLETED", label: "Complete" },
];

export function GenerationStatus({
  job,
  connected,
  className,
}: {
  job: GenerationJob;
  connected?: boolean;
  className?: string;
}) {
  const isCover = job.config.prompt.mode === "cover";
  const stages = ALL_STAGES.filter((stage) => !stage.coverOnly || isCover);
  const order = stages.map((stage) => stage.status);
  const currentIndex = order.indexOf(job.status);
  const failed = job.status === "FAILED";
  const cancelled = job.status === "CANCELLED";
  const incomplete = job.status === "INCOMPLETE";

  return (
    <div className={cn("rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-surface)] p-5", className)}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">Progress</h3>
        <div className="flex items-center gap-2">
          {job.cancel_requested && !["CANCELLED", "COMPLETED", "FAILED"].includes(job.status) ? (
            /* Cancellation is cooperative: the stage runs to its next safe
               boundary, so this stays up until the job actually settles. */
            <Badge tone="warn">Cancellation requested…</Badge>
          ) : null}
          {connected != null ? (
            <Badge tone={connected ? "accent" : "neutral"}>{connected ? "live" : "polling"}</Badge>
          ) : null}
        </div>
      </div>

      <ol className="space-y-2.5">
        {stages.map((stage) => {
          const stageIndex = order.indexOf(stage.status);
          const done = currentIndex > stageIndex || job.status === "COMPLETED" || (incomplete && stage.status !== "COMPLETED");
          const active = job.status === stage.status;
          const stopped = (failed || cancelled || incomplete) && stageIndex >= currentIndex;

          return (
            <li key={stage.status} className="flex items-start gap-3">
              <span className="mt-0.5 shrink-0">
                {active ? (
                  <Loader2 className="h-4 w-4 animate-spin text-[var(--color-accent)]" aria-label="in progress" />
                ) : done ? (
                  <Check className="h-4 w-4 text-[var(--color-accent)]" aria-label="done" />
                ) : stopped ? (
                  <X className="h-4 w-4 text-[var(--color-ink-faint)]" aria-label="not reached" />
                ) : (
                  <CircleDashed className="h-4 w-4 text-[var(--color-ink-faint)]" aria-label="pending" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <p
                  className={cn(
                    "text-sm",
                    active
                      ? "text-[var(--color-ink)]"
                      : done
                        ? "text-[var(--color-ink-muted)]"
                        : "text-[var(--color-ink-faint)]",
                  )}
                >
                  {active && job.progress.label
                    ? job.progress.label
                    : incomplete && stage.status === "COMPLETED"
                      ? "Stopped at the token limit"
                      : stage.label}
                </p>

                {active ? (
                  <div className="mt-1.5 space-y-1">
                    <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
                      <div
                        className={cn(
                          "h-full rounded-full bg-[var(--color-accent)]",
                          job.progress.percent != null
                            ? "transition-[width] duration-[var(--duration-slow)]"
                            : "w-1/3 animate-pulse",
                        )}
                        style={job.progress.percent != null ? { width: `${job.progress.percent}%` } : undefined}
                      />
                    </div>
                    <p className="text-xs tabular-nums text-[var(--color-ink-faint)]">
                      {job.progress.percent != null ? (
                        <>
                          {job.progress.completed?.toLocaleString()} / {job.progress.total?.toLocaleString()}{" "}
                          {job.progress.unit} · {job.progress.percent.toFixed(0)}%
                        </>
                      ) : (
                        <>
                          {formatCount(job.progress.completed, job.progress.unit)}
                          {job.progress.rate_per_second
                            ? ` · ${job.progress.rate_per_second.toFixed(0)}/s`
                            : ""}
                          {job.progress.unit === "tokens" ? " · no fixed target for this stage" : ""}
                        </>
                      )}
                    </p>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
