"use client";

import {
  AlertTriangle,
  Copy,
  Download,
  FileMusic,
  Heart,
  Loader2,
  MoreHorizontal,
  Music2,
  Pause,
  Play,
  RefreshCw,
  Settings2,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { DeleteGenerationDialog } from "@/components/library/delete-generation-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
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
  TRANSCRIBING: "info",
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
  "TRANSCRIBING",
  "PLANNING",
  "GENERATING",
  "DECODING",
  "POST_PROCESSING",
  "CANCEL_REQUESTED",
]);

export function GenerationCard({ job, layout = "list" }: { job: GenerationJob; layout?: "list" | "grid" }) {
  const { play, track, playing } = usePlayer();
  const { cancel, retry, duplicate, favorite, remove } = useGenerationActions();
  const [deleting, setDeleting] = React.useState(false);

  const audio = job.artifacts.find((artifact) => artifact.kind === "audio");
  const hasScore = job.artifacts.some((artifact) => artifact.kind === "score");
  const isCurrent = track?.id === job.id;
  const running = RUNNING.has(job.status);
  const truncated = Object.values(job.truncated ?? {}).some(Boolean);

  const playTrack = () =>
    audio &&
    play({
      id: job.id,
      title: job.title || "Untitled",
      style: job.config.prompt.style,
      src: api.audioUrl(job.id),
      durationSeconds: audio.duration_seconds,
    });

  const overflow = (
    <Menu>
      <MenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${job.title || "this generation"}`}>
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </MenuTrigger>
      <MenuContent align="end">
        {audio ? (
          <MenuItem onSelect={playTrack}>
            <Play className="h-4 w-4" />
            Play
          </MenuItem>
        ) : null}
        <MenuItem asChild>
          <Link href={`/generations/${job.id}`}>
            <Settings2 className="h-4 w-4" />
            Open
          </Link>
        </MenuItem>
        {hasScore ? (
          <MenuItem asChild>
            <Link href={`/scores/${job.id}`}>
              <FileMusic className="h-4 w-4" />
              View score
            </Link>
          </MenuItem>
        ) : null}
        {audio ? (
          <MenuItem asChild>
            <a href={api.downloadUrl(job.id)} download>
              <Download className="h-4 w-4" />
              Download
            </a>
          </MenuItem>
        ) : null}
        <MenuSeparator />
        {running ? (
          <MenuItem onSelect={() => cancel.mutate(job.id)}>
            <X className="h-4 w-4" />
            Cancel
          </MenuItem>
        ) : (
          <>
            <MenuItem onSelect={() => retry.mutate(job.id)}>
              <RefreshCw className="h-4 w-4" />
              Regenerate
            </MenuItem>
            <MenuItem
              onSelect={() =>
                duplicate.mutate({
                  id: job.id,
                  overrides: { sampling: { control_after_generate: "randomize" } },
                })
              }
            >
              <Copy className="h-4 w-4" />
              Duplicate settings
            </MenuItem>
          </>
        )}
        <MenuSeparator />
        <MenuItem
          destructive
          disabled={running}
          onSelect={(event) => {
            event.preventDefault();
            setDeleting(true);
          }}
        >
          <Trash2 className="h-4 w-4" />
          Delete
        </MenuItem>
      </MenuContent>
    </Menu>
  );

  const meta = (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge tone={TONE[job.status]}>{running && job.progress.label ? job.progress.label : job.status}</Badge>
      <Badge tone="outline">{job.config.prompt.mode}</Badge>
      {audio?.duration_seconds ? <Badge tone="outline">{formatDuration(audio.duration_seconds)}</Badge> : null}
      <Badge tone="outline">seed {job.config.sampling.seed}</Badge>
      {truncated ? (
        <Badge tone="warn" title="Generation stopped at its token limit; the song may end abruptly.">
          <AlertTriangle className="h-3 w-3" />
          truncated
        </Badge>
      ) : null}
    </div>
  );

  const progress = running ? (
    <div className="mt-3 space-y-1">
      <div className="h-1 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
        <div
          className={cn(
            "h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-[var(--duration-slow)]",
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
  ) : null;

  const playButton = (
    <button
      type="button"
      disabled={!audio}
      onClick={playTrack}
      aria-label={isCurrent && playing ? `Pause ${job.title}` : `Play ${job.title}`}
      className={cn(
        "grid shrink-0 place-items-center rounded-[var(--radius-md)] border transition-colors",
        layout === "grid" ? "h-12 w-12" : "h-14 w-14",
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
  );

  return (
    <>
      <Card interactive className={cn("overflow-hidden", isCurrent && "border-[var(--color-accent)]")}>
        <div className={cn("flex gap-4 p-4", layout === "grid" && "flex-col gap-3")}>
          <div className={cn("flex gap-4", layout === "grid" && "items-center gap-3")}>
            {playButton}
            {layout === "grid" ? (
              <div className="min-w-0 flex-1">
                <Link
                  href={`/generations/${job.id}`}
                  className="block truncate text-sm font-medium hover:text-[var(--color-accent)]"
                >
                  {job.title || "Untitled"}
                </Link>
                <p className="truncate text-xs text-[var(--color-ink-faint)]">
                  {formatRelative(job.requested_at)}
                </p>
              </div>
            ) : null}
            {layout === "grid" ? overflow : null}
          </div>

          <div className="min-w-0 flex-1">
            {layout === "list" ? (
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={`/generations/${job.id}`}
                  className="truncate text-sm font-medium hover:text-[var(--color-accent)]"
                >
                  {job.title || "Untitled"}
                </Link>
                <div className="flex shrink-0 items-center">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={job.favorite ? "Remove from favourites" : "Add to favourites"}
                    aria-pressed={job.favorite}
                    onClick={() => favorite.mutate({ id: job.id, favorite: !job.favorite })}
                  >
                    <Heart
                      className={cn("h-4 w-4", job.favorite && "fill-[var(--color-accent)] text-[var(--color-accent)]")}
                    />
                  </Button>
                  {overflow}
                </div>
              </div>
            ) : null}

            <p
              className={cn(
                "text-xs text-[var(--color-ink-faint)]",
                layout === "list" ? "mt-0.5 line-clamp-1" : "line-clamp-2",
              )}
            >
              {job.config.prompt.style || "No style"}
            </p>

            <div className="mt-2">{meta}</div>
            {layout === "list" ? (
              <span className="sr-only">Created {formatRelative(job.requested_at)}</span>
            ) : null}
            {progress}

            {job.status === "FAILED" && job.error_message ? (
              <p className="mt-2 line-clamp-2 text-xs text-[var(--color-danger)]">
                {job.error_code}: {job.error_message}
              </p>
            ) : null}
          </div>
        </div>
      </Card>

      <DeleteGenerationDialog
        job={job}
        open={deleting}
        onOpenChange={setDeleting}
        onDelete={(id) => remove.mutateAsync(id)}
      />
    </>
  );
}
