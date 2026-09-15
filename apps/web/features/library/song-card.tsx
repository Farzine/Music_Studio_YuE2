"use client";

import {
  AlertTriangle,
  Copy,
  Download,
  Heart,
  Loader2,
  Music2,
  Pause,
  Play,
  RefreshCw,
  Settings2,
  X,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tooltip } from "@/components/ui/controls";
import { useGenerationActions } from "@/hooks/use-queries";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDuration, formatRelative } from "@/lib/format";
import { usePlayer } from "@/store/player";
import type { GenerationJob, JobStatus } from "@/types/api";

const TONE: Record<JobStatus, "neutral" | "accent" | "warn" | "danger" | "info"> = {
  DRAFT: "neutral",
  QUEUED: "neutral",
  LOADING_MODEL: "info",
  PLANNING: "info",
  GENERATING: "info",
  DECODING: "info",
  POST_PROCESSING: "info",
  COMPLETED: "accent",
  FAILED: "danger",
  CANCEL_REQUESTED: "warn",
  CANCELLED: "warn",
};

const RUNNING = new Set<JobStatus>([
  "QUEUED",
  "LOADING_MODEL",
  "PLANNING",
  "GENERATING",
  "DECODING",
  "POST_PROCESSING",
  "CANCEL_REQUESTED",
]);

export function SongCard({ job }: { job: GenerationJob }) {
  const { play, track, playing } = usePlayer();
  const { cancel, retry, duplicate, favorite } = useGenerationActions();

  const audio = job.artifacts.find((artifact) => artifact.kind === "audio");
  const isCurrent = track?.id === job.id;
  const running = RUNNING.has(job.status);
  const truncated = Object.values(job.truncated ?? {}).some(Boolean);

  return (
    <Card className="group overflow-hidden transition-colors hover:border-[var(--color-ink-faint)]">
      <div className="flex items-start gap-4 p-4">
        <button
          type="button"
          disabled={!audio}
          onClick={() =>
            audio &&
            play({
              id: job.id,
              title: job.title || "Untitled",
              style: job.config.prompt.style,
              src: api.audioUrl(job.id),
              durationSeconds: audio.duration_seconds,
            })
          }
          aria-label={isCurrent && playing ? "Pause" : "Play"}
          className={cn(
            "grid h-16 w-16 shrink-0 place-items-center rounded-xl border transition-colors",
            audio
              ? "border-[var(--color-line)] bg-[var(--color-surface-2)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              : "cursor-not-allowed border-dashed border-[var(--color-line)] text-[var(--color-ink-faint)]",
          )}
        >
          {running ? (
            <Loader2 className="h-5 w-5 animate-spin text-[var(--color-accent)]" />
          ) : audio ? (
            isCurrent && playing ? (
              <Pause className="h-5 w-5" />
            ) : (
              <Play className="h-5 w-5 translate-x-[1px]" />
            )
          ) : (
            <Music2 className="h-5 w-5" />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <Link
              href={`/generations/${job.id}`}
              className="truncate text-sm font-medium hover:text-[var(--color-accent)]"
            >
              {job.title || "Untitled"}
            </Link>
            <Button
              variant="ghost"
              size="icon"
              aria-label={job.favorite ? "Remove from favourites" : "Add to favourites"}
              onClick={() => favorite.mutate({ id: job.id, favorite: !job.favorite })}
            >
              <Heart className={cn("h-4 w-4", job.favorite && "fill-[var(--color-accent)] text-[var(--color-accent)]")} />
            </Button>
          </div>

          <p className="mt-0.5 line-clamp-1 text-xs text-[var(--color-ink-faint)]">
            {job.config.prompt.style || "No style"}
          </p>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge tone={TONE[job.status]}>
              {running && job.progress.label ? job.progress.label : job.status}
            </Badge>
            <Badge>{job.config.prompt.mode}</Badge>
            {audio?.duration_seconds ? <Badge>{formatDuration(audio.duration_seconds)}</Badge> : null}
            <Badge>seed {job.config.sampling.seed}</Badge>
            {truncated ? (
              <Tooltip label="Generation stopped at its token limit; the song may end abruptly.">
                <span>
                  <Badge tone="warn">
                    <AlertTriangle className="h-3 w-3" />
                    truncated
                  </Badge>
                </span>
              </Tooltip>
            ) : null}
            <span className="ml-auto text-[11px] text-[var(--color-ink-faint)]">
              {formatRelative(job.requested_at)}
            </span>
          </div>

          {running ? (
            <div className="mt-3 space-y-1">
              <div className="h-1 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
                <div
                  className={cn(
                    "h-full rounded-full bg-[var(--color-accent)]",
                    job.progress.percent == null && "w-1/3 animate-pulse",
                  )}
                  style={job.progress.percent != null ? { width: `${job.progress.percent}%` } : undefined}
                />
              </div>
              <p className="text-[11px] text-[var(--color-ink-faint)]">
                {job.progress.percent != null
                  ? `${job.progress.label} · ${job.progress.percent.toFixed(0)}%`
                  : job.progress.completed
                    ? `${job.progress.label} · ${job.progress.completed.toLocaleString()} ${job.progress.unit ?? ""}`
                    : job.progress.label}
              </p>
            </div>
          ) : null}

          {job.status === "FAILED" && job.error_message ? (
            <p className="mt-2 line-clamp-2 text-xs text-[var(--color-danger)]">
              {job.error_code}: {job.error_message}
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-1.5 opacity-100 transition-opacity lg:opacity-0 lg:group-hover:opacity-100 lg:group-focus-within:opacity-100">
            {audio ? (
              <Button variant="ghost" size="sm" asChild>
                <a href={api.downloadUrl(job.id)} download>
                  <Download className="h-3.5 w-3.5" />
                  Download
                </a>
              </Button>
            ) : null}
            {running ? (
              <Button variant="ghost" size="sm" onClick={() => cancel.mutate(job.id)}>
                <X className="h-3.5 w-3.5" />
                Cancel
              </Button>
            ) : (
              <>
                <Button variant="ghost" size="sm" onClick={() => retry.mutate(job.id)}>
                  <RefreshCw className="h-3.5 w-3.5" />
                  Regenerate
                </Button>
                <Button variant="ghost" size="sm" onClick={() => duplicate.mutate({ id: job.id })}>
                  <Copy className="h-3.5 w-3.5" />
                  Duplicate
                </Button>
              </>
            )}
            <Button variant="ghost" size="sm" asChild>
              <Link href={`/generations/${job.id}`}>
                <Settings2 className="h-3.5 w-3.5" />
                Details
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
