"use client";

import {
  AlertTriangle,
  Download,
  FileMusic,
  GitBranch,
  Loader2,
  Music2,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Settings2,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useGenerationActions } from "@/hooks/use-queries";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDuration } from "@/lib/format";
import { useDeleteTarget } from "@/store/delete-target";
import { useGenerationTarget } from "@/store/generation-target";
import { usePlayer } from "@/store/player";
import type { GenerationJob, JobStatus } from "@/types/api";

const TONE: Record<JobStatus, "neutral" | "accent" | "warn" | "danger" | "info"> = {
  DRAFT: "neutral",
  QUEUED: "neutral",
  LOADING_MODEL: "info",
  TRANSCRIBING: "info",
  PLANNING: "info",
  GENERATING: "info",
  DECODING: "info",
  POST_PROCESSING: "info",
  COMPLETED: "accent",
  INCOMPLETE: "warn",
  FAILED: "danger",
  CANCEL_REQUESTED: "warn",
  CANCELLED: "warn",
};

const RUNNING = new Set<JobStatus>([
  "QUEUED",
  "LOADING_MODEL",
  "TRANSCRIBING",
  "PLANNING",
  "GENERATING",
  "DECODING",
  "POST_PROCESSING",
  "CANCEL_REQUESTED",
]);

function modelLabel(job: GenerationJob): string {
  const checkpoint = String(job.config.model.checkpoint ?? "default");
  if (checkpoint === "default") return "default model";
  return checkpoint.split("/").pop() ?? checkpoint;
}

/**
 * One version in a project's history.
 *
 * Every action the version supports is on the row, because this is the page
 * the user manages a song from: play it, start a new version from its
 * settings, rename it, download it, or delete just this one.
 */
function HistoryRow({ job, versionOf }: { job: GenerationJob; versionOf: Map<string, number> }) {
  const { play, track, playing } = usePlayer();
  const { cancel } = useGenerationActions();
  const requestDelete = useDeleteTarget((state) => state.request);
  const requestDialog = useGenerationTarget((state) => state.request);

  const audio = job.artifacts.find((artifact) => artifact.kind === "audio");
  const hasScore = job.artifacts.some((artifact) => artifact.kind === "score");
  const isCurrent = track?.id === job.id;
  const running = RUNNING.has(job.status);
  const parentVersion = job.parent_generation_id ? versionOf.get(job.parent_generation_id) : undefined;

  const playTrack = () =>
    audio &&
    play({
      id: job.id,
      title: job.title || "Untitled",
      style: job.config.prompt.style,
      src: api.audioUrl(job.id),
      durationSeconds: audio.duration_seconds,
    });

  return (
    <Card className={cn("overflow-hidden", isCurrent && "border-[var(--color-accent)]")}>
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:gap-4">
        <button
          type="button"
          disabled={!audio}
          onClick={playTrack}
          aria-label={isCurrent && playing ? `Pause version ${job.version}` : `Play version ${job.version}`}
          className={cn(
            "grid h-12 w-12 shrink-0 place-items-center rounded-[var(--radius-md)] border transition-colors",
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
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <Link
              href={`/generations/${job.id}`}
              className="text-sm font-semibold hover:text-[var(--color-accent)]"
            >
              Version {job.version}
            </Link>
            <span className="min-w-0 truncate text-sm text-[var(--color-ink-muted)]">
              {job.title || "Untitled"}
            </span>
          </div>

          <p className="mt-0.5 text-xs text-[var(--color-ink-faint)]">{formatDateTime(job.requested_at)}</p>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge tone={TONE[job.status]}>
              {running && job.progress.label ? job.progress.label : job.status}
            </Badge>
            <Badge tone="outline">{job.config.prompt.mode}</Badge>
            {audio?.duration_seconds ? (
              <Badge tone="outline">{formatDuration(audio.duration_seconds)}</Badge>
            ) : null}
            <Badge tone="outline">{modelLabel(job)}</Badge>
            <Badge tone="outline">seed {job.config.sampling.seed}</Badge>
            {parentVersion ? (
              <Badge tone="outline" title="This version was started from an earlier one">
                <GitBranch className="h-3 w-3" />
                from v{parentVersion}
              </Badge>
            ) : null}
            {job.status === "INCOMPLETE" ? (
              <Badge tone="warn" title="Stopped at its token limit before the song ended.">
                <AlertTriangle className="h-3 w-3" />
                unfinished
              </Badge>
            ) : null}
          </div>

          {job.config.prompt.style ? (
            <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-[var(--color-ink-faint)]">
              {job.config.prompt.style}
            </p>
          ) : null}

          {job.status === "FAILED" && job.error_message ? (
            <p className="mt-2 line-clamp-2 text-xs text-[var(--color-danger)]">
              {job.error_code}: {job.error_message}
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-1.5">
            {audio ? (
              <Button variant="surface" size="xs" onClick={playTrack}>
                <Play className="h-3.5 w-3.5" />
                Play
              </Button>
            ) : null}
            {running ? (
              <Button variant="danger" size="xs" onClick={() => cancel.mutate(job.id)}>
                <X className="h-3.5 w-3.5" />
                Cancel
              </Button>
            ) : (
              <Button variant="surface" size="xs" asChild>
                <Link href={`/create?from=${job.id}`}>
                  <RefreshCw className="h-3.5 w-3.5" />
                  Regenerate
                </Link>
              </Button>
            )}
            <Button
              variant="surface"
              size="xs"
              onClick={() => requestAnimationFrame(() => requestDialog("rename", job))}
            >
              <Pencil className="h-3.5 w-3.5" />
              Rename
            </Button>
            {audio ? (
              <Button
                variant="surface"
                size="xs"
                onClick={() => requestAnimationFrame(() => requestDialog("download", job))}
              >
                <Download className="h-3.5 w-3.5" />
                Download
              </Button>
            ) : null}
            {hasScore ? (
              <Button variant="surface" size="xs" asChild>
                <Link href={`/scores/${job.id}`}>
                  <FileMusic className="h-3.5 w-3.5" />
                  Score
                </Link>
              </Button>
            ) : null}
            <Button variant="ghost" size="xs" asChild>
              <Link href={`/generations/${job.id}`}>
                <Settings2 className="h-3.5 w-3.5" />
                Details
              </Link>
            </Button>
            <Button
              variant="ghost"
              size="xs"
              disabled={running}
              className="text-[var(--color-danger)]"
              onClick={() => requestAnimationFrame(() => requestDelete(job))}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

/** A project's complete generation history, newest version first. */
export function GenerationHistory({ generations }: { generations: GenerationJob[] }) {
  const versionOf = React.useMemo(
    () => new Map(generations.map((job) => [job.id, job.version])),
    [generations],
  );

  return (
    <div className="space-y-3">
      {generations.map((job) => (
        <HistoryRow key={job.id} job={job} versionOf={versionOf} />
      ))}
    </div>
  );
}
