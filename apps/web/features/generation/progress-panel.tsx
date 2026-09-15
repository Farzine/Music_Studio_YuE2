"use client";

import { Check, CircleDashed, Loader2, X } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatCount } from "@/lib/format";
import type { GenerationJob, JobStatus } from "@/types/api";

/** The stages the backend actually reports, in the order it reports them. */
const STAGES: { status: JobStatus; label: string }[] = [
  { status: "QUEUED", label: "Queued" },
  { status: "LOADING_MODEL", label: "Loading model" },
  { status: "PLANNING", label: "Planning composition" },
  { status: "GENERATING", label: "Generating audio" },
  { status: "DECODING", label: "Decoding" },
  { status: "POST_PROCESSING", label: "Saving artifacts" },
  { status: "COMPLETED", label: "Complete" },
];

const ORDER = STAGES.map((stage) => stage.status);

export function ProgressPanel({ job, connected }: { job: GenerationJob; connected: boolean }) {
  const failed = job.status === "FAILED";
  const cancelled = job.status === "CANCELLED";
  const currentIndex = ORDER.indexOf(job.status);

  return (
    <div className="rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface)] p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">Progress</h3>
        <div className="flex items-center gap-2">
          {job.cancel_requested && !["CANCELLED", "COMPLETED", "FAILED"].includes(job.status) ? (
            /* Cancellation is cooperative: the stage keeps running until its
               next safe boundary, so the badge stays until the job settles. */
            <Badge tone="warn">Cancellation requested…</Badge>
          ) : null}
          <Badge tone={connected ? "accent" : "neutral"}>{connected ? "live" : "polling"}</Badge>
        </div>
      </div>

      <ol className="space-y-2.5">
        {STAGES.map((stage, index) => {
          const stageIndex = ORDER.indexOf(stage.status);
          const done = currentIndex > stageIndex || job.status === "COMPLETED";
          const active = job.status === stage.status;
          const stopped = (failed || cancelled) && stageIndex >= currentIndex;
          return (
            <li key={stage.status} className="flex items-start gap-3">
              <span className="mt-0.5">
                {active ? (
                  <Loader2 className="h-4 w-4 animate-spin text-[var(--color-accent)]" />
                ) : done ? (
                  <Check className="h-4 w-4 text-[var(--color-accent)]" />
                ) : stopped ? (
                  <X className="h-4 w-4 text-[var(--color-ink-faint)]" />
                ) : (
                  <CircleDashed className="h-4 w-4 text-[var(--color-ink-faint)]" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <p
                  className={cn(
                    "text-sm",
                    active ? "text-[var(--color-ink)]" : done ? "text-[var(--color-ink-muted)]" : "text-[var(--color-ink-faint)]",
                  )}
                >
                  {active && job.progress.label ? job.progress.label : stage.label}
                </p>
                {active ? (
                  <div className="mt-1.5 space-y-1">
                    {job.progress.percent != null ? (
                      <>
                        <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
                          <div
                            className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-300"
                            style={{ width: `${job.progress.percent}%` }}
                          />
                        </div>
                        <p className="text-xs tabular-nums text-[var(--color-ink-faint)]">
                          {job.progress.completed?.toLocaleString()} / {job.progress.total?.toLocaleString()}{" "}
                          {job.progress.unit} · {job.progress.percent.toFixed(0)}%
                        </p>
                      </>
                    ) : (
                      <>
                        {/* No target exists for this stage, so no percentage is shown. */}
                        <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
                          <div className="h-full w-1/3 animate-pulse rounded-full bg-[var(--color-accent)]" />
                        </div>
                        <p className="text-xs tabular-nums text-[var(--color-ink-faint)]">
                          {formatCount(job.progress.completed, job.progress.unit)}
                          {job.progress.rate_per_second
                            ? ` · ${job.progress.rate_per_second.toFixed(0)}/s`
                            : ""}
                          {job.progress.unit === "tokens" ? " · no fixed target for this stage" : ""}
                        </p>
                      </>
                    )}
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
