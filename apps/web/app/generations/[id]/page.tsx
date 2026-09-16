"use client";

import {
  ArrowLeft,
  Copy,
  Download,
  FileMusic,
  GitBranch,
  Heart,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { GenerationStatus } from "@/components/generation/generation-status";
import { TechnicalDetails } from "@/features/generation/technical-details";
import { Waveform, usePeaks } from "@/features/player/waveform";
import { useGeneration, useGenerationActions, useJobLog } from "@/hooks/use-queries";
import { useGenerationStream } from "@/hooks/use-generation-stream";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDuration } from "@/lib/format";
import { useDeleteTarget } from "@/store/delete-target";
import { useGenerationTarget } from "@/store/generation-target";
import { usePlayer } from "@/store/player";

export default function GenerationPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id;
  const { data, isLoading } = useGeneration(id);
  const { job: streamed, connected } = useGenerationStream(id);
  const { data: log } = useJobLog(id);
  const { cancel, retry, duplicate, favorite } = useGenerationActions();
  const requestDelete = useDeleteTarget((state) => state.request);
  const requestDialog = useGenerationTarget((state) => state.request);
  const { play, track, playing, currentTime, duration, requestSeek } = usePlayer();

  const job = streamed ?? data?.generation;
  const audio = job?.artifacts.find((artifact) => artifact.kind === "audio");
  const hasScore = job?.artifacts.some((artifact) => artifact.kind === "score");
  const isCurrent = track?.id === job?.id;
  const { peaks } = usePeaks(isCurrent && audio ? api.audioUrl(job!.id) : null);
  const running = job ? !["COMPLETED", "FAILED", "CANCELLED"].includes(job.status) : false;

  if (isLoading || !job) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <h1 className="min-w-0 flex-1 truncate text-xl font-semibold tracking-tight">
          {job.title || "Untitled"}
        </h1>
        <Button
          variant="ghost"
          size="icon"
          aria-label={job.favorite ? "Remove from favourites" : "Add to favourites"}
          aria-pressed={job.favorite}
          onClick={() => favorite.mutate({ id: job.id, favorite: !job.favorite })}
        >
          <Heart className={cn("h-4 w-4", job.favorite && "fill-[var(--color-accent)] text-[var(--color-accent)]")} />
        </Button>
        <Menu>
          <MenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="More actions">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </MenuTrigger>
          <MenuContent align="end">
            <MenuItem asChild>
              <Link href={`/projects/${job.project_id}`}>Open project</Link>
            </MenuItem>
            <MenuItem onSelect={() => requestAnimationFrame(() => requestDialog("rename", job))}>
              <Pencil className="h-4 w-4" />
              Rename
            </MenuItem>
            <MenuItem asChild>
              <Link href={`/create?from=${job.id}`}>
                <RefreshCw className="h-4 w-4" />
                Regenerate…
              </Link>
            </MenuItem>
            <MenuItem onSelect={() => duplicate.mutate({ id: job.id })}>Run again unchanged</MenuItem>
            <MenuSeparator />
            <MenuItem
              destructive
              disabled={running}
              onSelect={() => {
                // See GenerationCard: close the menu before opening the dialog.
                requestAnimationFrame(() => requestDelete(job, { redirectTo: "/library" }));
              }}
            >
              <Trash2 className="h-4 w-4" />
              Delete
            </MenuItem>
          </MenuContent>
        </Menu>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-5">
          <Card>
            <CardContent className="space-y-4 p-5">
              <div className="flex flex-wrap gap-1.5">
                <Badge tone={job.status === "COMPLETED" ? "accent" : job.status === "FAILED" ? "danger" : "info"}>
                  {job.status}
                </Badge>
                <Badge>version {job.version}</Badge>
                <Badge>{job.config.prompt.mode}</Badge>
                <Badge>seed {job.config.sampling.seed}</Badge>
                <Badge>{String(job.config.model.checkpoint || "default model")}</Badge>
                <Badge>{job.config.output.format}</Badge>
                {audio?.duration_seconds ? <Badge>{formatDuration(audio.duration_seconds)}</Badge> : null}
                <span className="ml-auto text-xs text-[var(--color-ink-faint)]">
                  {formatDateTime(job.requested_at)}
                </span>
              </div>

              {job.parent_generation_id ? (
                <p className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--color-ink-faint)]">
                  <GitBranch className="h-3.5 w-3.5" />
                  Started from an earlier version, which is unchanged.
                  <Link
                    href={`/generations/${job.parent_generation_id}`}
                    className="underline underline-offset-2 hover:text-[var(--color-ink)]"
                  >
                    Open it
                  </Link>
                </p>
              ) : null}

              {audio ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-3">
                    <Button
                      variant="primary"
                      size="icon"
                      className="h-11 w-11 shrink-0 rounded-full"
                      aria-label={isCurrent && playing ? "Pause" : "Play"}
                      onClick={() =>
                        play({
                          id: job.id,
                          title: job.title || "Untitled",
                          style: job.config.prompt.style,
                          src: api.audioUrl(job.id),
                          durationSeconds: audio.duration_seconds,
                        })
                      }
                    >
                      {isCurrent && playing ? (
                        <Pause className="h-4 w-4" />
                      ) : (
                        <Play className="h-4 w-4 translate-x-[1px]" />
                      )}
                    </Button>
                    <div className="min-w-0 flex-1">
                      <Waveform
                        peaks={isCurrent ? peaks : null}
                        progress={isCurrent && duration ? currentTime / duration : 0}
                        height={52}
                        onSeek={(ratio) => isCurrent && requestSeek(ratio * duration)}
                      />
                      <div className="mt-1 flex justify-between text-[11px] tabular-nums text-[var(--color-ink-faint)]">
                        <span>{formatDuration(isCurrent ? currentTime : 0)}</span>
                        <span>
                          {audio.sample_rate} Hz · {audio.channels === 2 ? "stereo" : "mono"} ·{" "}
                          {formatDuration(audio.duration_seconds)}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ) : running ? (
                <p className="text-sm text-[var(--color-ink-muted)]">Audio appears here when the run finishes.</p>
              ) : null}

              <div className="flex flex-wrap gap-2">
                {audio ? (
                  <Button
                    variant="surface"
                    size="sm"
                    onClick={() => requestAnimationFrame(() => requestDialog("download", job))}
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download…
                  </Button>
                ) : null}
                {running ? (
                  <Button variant="danger" size="sm" onClick={() => cancel.mutate(job.id)}>
                    <X className="h-3.5 w-3.5" />
                    Cancel
                  </Button>
                ) : (
                  <>
                    <Button variant="surface" size="sm" asChild>
                      <Link href={`/create?from=${job.id}`}>
                        <RefreshCw className="h-3.5 w-3.5" />
                        Regenerate…
                      </Link>
                    </Button>
                    <Button
                      variant="surface"
                      size="sm"
                      onClick={() =>
                        duplicate.mutate({
                          id: job.id,
                          overrides: { sampling: { control_after_generate: "randomize" } },
                        })
                      }
                    >
                      <Copy className="h-3.5 w-3.5" />
                      New variation
                    </Button>
                  </>
                )}
                {hasScore ? (
                  <Button variant="surface" size="sm" asChild>
                    <Link href={`/scores/${job.id}`}>
                      <FileMusic className="h-3.5 w-3.5" />
                      View score
                    </Link>
                  </Button>
                ) : null}
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/projects/${job.project_id}`}>Open project</Link>
                </Button>
              </div>

              {job.effective_adjustments.length > 0 ? (
                <WarningNotice>
                  <p className="font-medium">A limit was adjusted for this run</p>
                  <ul className="mt-1.5 space-y-1">
                    {job.effective_adjustments.map((adjustment) => (
                      <li key={adjustment.parameter} className="text-[var(--color-ink-muted)]">
                        <span className="font-mono text-xs">{adjustment.parameter}</span>: requested{" "}
                        {adjustment.requested}
                        {adjustment.unit === "seconds" ? "s" : ""}, used {adjustment.effective}
                        {adjustment.unit === "seconds" ? "s" : ""} — {adjustment.reason}
                      </li>
                    ))}
                  </ul>
                </WarningNotice>
              ) : null}

              {job.status === "INCOMPLETE" ? (
                <WarningNotice>
                  <p className="font-medium">This song did not reach its ending</p>
                  <p className="mt-1 text-[var(--color-ink-muted)]">
                    Generation stopped at its token limit after{" "}
                    {(job.budget?.semantic?.tokens_generated ?? 0).toLocaleString()} of{" "}
                    {(job.budget?.semantic?.budget_tokens ?? 0).toLocaleString()} audio tokens, so the
                    audio below is part of a song rather than a finished one. It is kept so you can hear
                    it, and is not counted as a completed generation.
                  </p>
                  <p className="mt-1.5 text-[var(--color-ink-muted)]">{job.error_guidance}</p>
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    <Button
                      variant="surface"
                      size="sm"
                      onClick={() =>
                        duplicate.mutate({
                          id: job.id,
                          overrides: {
                            sampling: {
                              max_duration_seconds: Math.min(
                                960,
                                Math.ceil(((job.budget?.semantic?.tokens_generated ?? 0) / 25) * 2),
                              ),
                            },
                          },
                        })
                      }
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Retry with a longer limit
                    </Button>
                  </div>
                </WarningNotice>
              ) : null}

              {job.warnings.length > 0 ? (
                <WarningNotice>
                  <ul className="list-disc space-y-1 pl-4">
                    {job.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </WarningNotice>
              ) : null}

              {job.error_message ? (
                <ErrorNotice
                  title={(job.error_code ?? "Failed").replace(/_/g, " ").toLowerCase()}
                  message={job.error_message}
                  guidance={job.error_guidance}
                  actions={
                    <>
                      <Button variant="surface" size="sm" onClick={() => retry.mutate(job.id)}>
                        <RefreshCw className="h-3.5 w-3.5" />
                        Retry
                      </Button>
                      <Button variant="ghost" size="sm" asChild>
                        <Link href="/create">Adjust settings</Link>
                      </Button>
                    </>
                  }
                />
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Prompt</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
                  Style
                </p>
                <p className="text-sm leading-relaxed">{job.config.prompt.style || "—"}</p>
              </div>
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
                  Lyrics
                </p>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-md)] bg-[var(--color-canvas)] p-3 font-mono text-xs leading-relaxed">
                  {job.config.prompt.lyrics || "—"}
                </pre>
              </div>
            </CardContent>
          </Card>

          <TechnicalDetails job={job} />
        </div>

        <aside className="min-w-0 space-y-5">
          <GenerationStatus job={job} connected={connected} />

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Log</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="max-h-80 space-y-1.5 overflow-y-auto">
                {(log?.items ?? []).map((entry, index) => (
                  <div key={`${entry.timestamp}-${index}`} className="text-xs">
                    <span
                      className={cn(
                        "mr-2 font-mono",
                        entry.severity === "ERROR"
                          ? "text-[var(--color-danger)]"
                          : entry.severity === "WARNING"
                            ? "text-[var(--color-warn)]"
                            : "text-[var(--color-ink-faint)]",
                      )}
                    >
                      {entry.stage}
                    </span>
                    <span className="text-[var(--color-ink-muted)]">{entry.message}</span>
                  </div>
                ))}
                {(log?.items ?? []).length === 0 ? (
                  <p className="text-xs text-[var(--color-ink-faint)]">No log entries yet.</p>
                ) : null}
              </div>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
