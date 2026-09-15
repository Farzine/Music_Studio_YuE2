"use client";

import { ArrowLeft, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { SongCard } from "@/features/library/song-card";
import { useProject } from "@/hooks/use-queries";
import { formatDateTime } from "@/lib/format";

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { data, isLoading } = useProject(params?.id);

  if (isLoading || !data) return <Skeleton className="h-96 w-full" />;

  const { project, generations } = data;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <h1 className="min-w-0 flex-1 truncate text-xl font-semibold tracking-tight">
          {project.title || "Untitled project"}
        </h1>
        <Button variant="primary" size="sm" asChild>
          <Link href="/create">
            <Sparkles className="h-3.5 w-3.5" />
            New generation
          </Link>
        </Button>
      </div>

      <div className="grid gap-5 lg:grid-cols-[22rem_minmax(0,1fr)]">
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
              <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded-xl bg-[var(--color-canvas)] p-3 font-mono text-xs">
                {project.lyrics || "—"}
              </pre>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{project.mode}</Badge>
              <Badge>{generations.length} generations</Badge>
            </div>
            <p className="text-xs text-[var(--color-ink-faint)]">
              Updated {formatDateTime(project.updated_at)}
            </p>
          </CardContent>
        </Card>

        <div className="min-w-0 space-y-3">
          {generations.length > 0 ? (
            generations.map((job) => <SongCard key={job.id} job={job} />)
          ) : (
            <EmptyState title="No generations in this project yet" />
          )}
        </div>
      </div>
    </div>
  );
}
