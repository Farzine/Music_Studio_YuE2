"use client";

import { ArrowLeft, History, Pencil, Sliders, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";

import { GenerationHistory } from "@/components/projects/generation-history";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { useProject } from "@/hooks/use-queries";
import { ApiRequestError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useProjectTarget } from "@/store/project-target";

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { data, isLoading, error } = useProject(params?.id);
  const request = useProjectTarget((state) => state.request);

  if (error) {
    return (
      <ErrorNotice
        title="Project unavailable"
        message={error instanceof ApiRequestError ? error.message : "This project could not be loaded."}
        actions={
          <Button variant="surface" size="sm" asChild>
            <Link href="/projects">Back to projects</Link>
          </Button>
        }
      />
    );
  }

  if (isLoading || !data) return <Skeleton className="h-96 w-full" />;

  const { project, generations } = data;
  const playable = generations.filter((job) => job.artifacts.some((item) => item.kind === "audio"));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <h1 className="min-w-0 flex-1 truncate text-xl font-semibold tracking-tight" title={project.title}>
          {project.title || "Untitled project"}
        </h1>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => requestAnimationFrame(() => request("rename", project))}
        >
          <Pencil className="h-3.5 w-3.5" />
          Rename
        </Button>
        <Button variant="surface" size="sm" asChild>
          <Link href={`/projects/${project.id}/settings`}>
            <Sliders className="h-3.5 w-3.5" />
            Configuration
          </Link>
        </Button>
        <Button variant="primary" size="sm" asChild>
          <Link href={`/create?project=${project.id}`}>
            <Sparkles className="h-3.5 w-3.5" />
            New version
          </Link>
        </Button>
      </div>

      <div className="grid gap-5 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card className="h-fit">
            <CardHeader className="pb-2">
              <CardTitle>Project</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div>
                <p className="text-xs uppercase tracking-wide text-[var(--color-ink-faint)]">Style</p>
                <p className="mt-1 leading-relaxed">{project.style || "—"}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-[var(--color-ink-faint)]">Lyrics</p>
                <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-md)] bg-[var(--color-canvas)] p-3 font-mono text-xs">
                  {project.lyrics || "—"}
                </pre>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{project.mode}</Badge>
                <Badge tone={generations.length > 0 ? "accent" : "neutral"}>
                  {generations.length} version{generations.length === 1 ? "" : "s"}
                </Badge>
                {playable.length > 0 ? <Badge tone="outline">{playable.length} with audio</Badge> : null}
              </div>
              <p className="text-xs text-[var(--color-ink-faint)]">
                Updated {formatDateTime(project.updated_at)}
              </p>
              <p className="text-xs leading-relaxed text-[var(--color-ink-faint)]">
                These are the project&apos;s current settings. Each version below keeps the settings it
                actually ran with, which never change.
              </p>
            </CardContent>
          </Card>

          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-[var(--color-danger)]"
            onClick={() =>
              requestAnimationFrame(() => request("delete", project, { redirectTo: "/projects" }))
            }
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete this project
          </Button>
        </div>

        <div className="min-w-0 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <History className="h-4 w-4 text-[var(--color-ink-faint)]" />
              Generation history
            </h2>
            <span className="text-xs text-[var(--color-ink-faint)]">newest first</span>
          </div>

          {generations.length > 0 ? (
            <GenerationHistory generations={generations} />
          ) : (
            <EmptyState
              title="No versions in this project yet"
              description="Start one from the project's settings, and every take you make will be listed here."
              action={
                <Button variant="primary" size="sm" asChild>
                  <Link href={`/create?project=${project.id}`}>Create the first version</Link>
                </Button>
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
