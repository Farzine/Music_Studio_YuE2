"use client";

import { ChevronUp, Loader2, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useGenerationActions, useQueue } from "@/hooks/use-queries";
import { cn } from "@/lib/cn";
import { formatCount, formatDuration } from "@/lib/format";
import { usePlayer } from "@/store/player";

/** Bottom-right drawer showing exactly what the worker and queue are doing. */
export function QueueDrawer() {
  const { data } = useQueue();
  const { cancel } = useGenerationActions();
  const hasTrack = usePlayer((state) => Boolean(state.track));
  const [open, setOpen] = React.useState(false);

  const active = data?.active ?? [];
  const queued = data?.queued ?? [];
  if (active.length === 0 && queued.length === 0) return null;

  const current = active[0];

  return (
    <div
      className="fixed right-3 z-20 w-[min(24rem,calc(100vw-1.5rem))] sm:right-6"
      style={{
        bottom: `calc(var(--mobile-nav-height) + ${hasTrack ? "var(--player-height)" : "0px"} + env(safe-area-inset-bottom) + 0.75rem)`,
      }}
    >
      <div className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[color-mix(in_oklch,var(--color-surface)_95%,transparent)] shadow-[var(--shadow-lg)] backdrop-blur-xl">
        <button
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--color-surface-2)]"
          aria-expanded={open}
        >
          {active.length > 0 ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-[var(--color-accent)]" />
          ) : (
            <span className="h-2 w-2 shrink-0 rounded-full bg-[var(--color-ink-faint)]" />
          )}
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {current ? `${current.progress.label}: ${current.title || "Untitled"}` : "Waiting for the worker"}
            </p>
            <p className="text-xs text-[var(--color-ink-faint)]">
              {queued.length > 0 ? `${queued.length} queued` : "Nothing else queued"}
              {data ? ` · GPU limit ${data.max_concurrent_gpu_jobs}` : null}
            </p>
          </div>
          <ChevronUp className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        </button>

        {open ? (
          <div className="max-h-80 overflow-y-auto border-t border-[var(--color-line)] p-2">
            {active.map((job) => (
              <div key={job.id} className="rounded-[var(--radius-sm)] p-2 hover:bg-[var(--color-surface-2)]">
                <div className="flex items-center justify-between gap-2">
                  <Link href={`/generations/${job.id}`} className="truncate text-sm hover:text-[var(--color-accent)]">
                    {job.title || "Untitled"}
                  </Link>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Cancel"
                    onClick={() => cancel.mutate(job.id)}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs text-[var(--color-ink-faint)]">
                  <Badge tone="accent">{job.status}</Badge>
                  <span>{job.progress.label}</span>
                  {job.progress.percent != null ? (
                    <span className="tabular-nums">{job.progress.percent.toFixed(0)}%</span>
                  ) : job.progress.completed ? (
                    <span className="tabular-nums">
                      {formatCount(job.progress.completed, job.progress.unit)}
                    </span>
                  ) : null}
                  <span className="ml-auto tabular-nums">{formatDuration(job.elapsed_seconds)}</span>
                </div>
              </div>
            ))}
            {queued.map((job) => (
              <div key={job.id} className="flex items-center justify-between gap-2 rounded-[var(--radius-sm)] p-2 hover:bg-[var(--color-surface-2)]">
                <div className="min-w-0">
                  <Link href={`/generations/${job.id}`} className="block truncate text-sm hover:text-[var(--color-accent)]">
                    {job.title || "Untitled"}
                  </Link>
                  <p className="text-xs text-[var(--color-ink-faint)]">
                    Position {job.queue_position} · waiting {formatDuration(job.waiting_seconds)}
                  </p>
                </div>
                <Button variant="ghost" size="icon" aria-label="Cancel" onClick={() => cancel.mutate(job.id)}>
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
