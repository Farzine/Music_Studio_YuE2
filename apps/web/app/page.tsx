"use client";

import { FolderOpen, Sparkles } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { GenerationCard } from "@/components/library/generation-card";
import { useGenerations, useProjects } from "@/hooks/use-queries";
import { formatRelative } from "@/lib/format";

export default function DashboardPage() {
  const { data: projects, isLoading: projectsLoading } = useProjects();
  const { data: recent, isLoading: recentLoading } = useGenerations({ limit: 6 });

  return (
    <div className="space-y-8">
      <section className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-surface)] p-6 sm:p-8">
        <p className="text-xs uppercase tracking-[0.2em] text-[var(--color-ink-faint)]">Local-first</p>
        <h1 className="text-balance-tight mt-2 max-w-2xl text-2xl font-semibold leading-tight tracking-tight sm:text-3xl lg:text-4xl">
          Make a whole song from a style and a few lines.
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-[var(--color-ink-muted)]">
          Everything runs on this machine with the open YuE2-3B model. Each generation keeps its exact settings,
          its score and a manifest, so you can always hear what changed and why.
        </p>
        <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button variant="primary" asChild>
            <Link href="/create">
              <Sparkles className="h-4 w-4" />
              Start creating
            </Link>
          </Button>
          <Button variant="surface" asChild>
            <Link href="/library">Browse the library</Link>
          </Button>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Projects</h2>
          <span className="text-xs text-[var(--color-ink-faint)]">{projects?.items.length ?? 0}</span>
        </div>
        {projectsLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-24 w-full" />
            ))}
          </div>
        ) : projects && projects.items.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {projects.items.slice(0, 9).map((project) => (
              <Link key={project.id} href={`/projects/${project.id}`}>
                <Card className="h-full transition-colors hover:border-[var(--color-ink-faint)]">
                  <CardContent className="p-4">
                    <p className="truncate text-sm font-medium">{project.title || "Untitled project"}</p>
                    <p className="mt-1 line-clamp-2 text-xs text-[var(--color-ink-faint)]">
                      {project.style || "No style yet"}
                    </p>
                    <div className="mt-3 flex items-center gap-2">
                      <Badge>{project.mode}</Badge>
                      <span className="text-[11px] text-[var(--color-ink-faint)]">
                        {formatRelative(project.updated_at)}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<FolderOpen className="h-6 w-6" />}
            title="No projects yet"
            description="A project is created the first time you generate. It keeps every take of the same song together."
            action={
              <Button variant="primary" size="sm" asChild>
                <Link href="/create">Create the first one</Link>
              </Button>
            }
          />
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Recent generations</h2>
          <Link href="/library" className="text-xs text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]">
            View all
          </Link>
        </div>
        {recentLoading ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {[0, 1].map((index) => (
              <Skeleton key={index} className="h-32 w-full" />
            ))}
          </div>
        ) : recent && recent.items.length > 0 ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {recent.items.map((job) => (
              <GenerationCard key={job.id} job={job} />
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}
