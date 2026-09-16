"use client";

import { FolderOpen, Search, Sparkles, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { ProjectCard } from "@/components/projects/project-card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { Input } from "@/components/ui/field";
import { useProjects } from "@/hooks/use-queries";
import type { ProjectSummary } from "@/types/api";

type Sort = "recent" | "created" | "title" | "versions";

const SORTS: { value: Sort; label: string }[] = [
  { value: "recent", label: "Recently active" },
  { value: "created", label: "Newest project" },
  { value: "title", label: "Title A–Z" },
  { value: "versions", label: "Most versions" },
];

function activity(project: ProjectSummary): string {
  return project.latest_generation_at ?? project.updated_at;
}

export default function ProjectsPage() {
  const { data, isLoading } = useProjects();
  const [search, setSearch] = React.useState("");
  const [sort, setSort] = React.useState<Sort>("recent");

  const items = React.useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = (data?.items ?? []).filter((project) =>
      needle
        ? `${project.title} ${project.style} ${project.tags.join(" ")}`.toLowerCase().includes(needle)
        : true,
    );
    const sorters: Record<Sort, (a: ProjectSummary, b: ProjectSummary) => number> = {
      recent: (a, b) => activity(b).localeCompare(activity(a)),
      created: (a, b) => b.created_at.localeCompare(a.created_at),
      title: (a, b) => (a.title || "Untitled").localeCompare(b.title || "Untitled"),
      versions: (a, b) => b.generation_count - a.generation_count,
    };
    return [...filtered].sort(sorters[sort]);
  }, [data, search, sort]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-semibold tracking-tight">Projects</h1>
          <span className="text-sm text-[var(--color-ink-faint)]">
            {isLoading ? "…" : `${items.length} of ${data?.items.length ?? 0}`}
          </span>
        </div>
        <Button variant="primary" size="sm" asChild>
          <Link href="/create">
            <Sparkles className="h-3.5 w-3.5" />
            New project
          </Link>
        </Button>
      </div>

      <p className="max-w-prose text-sm leading-relaxed text-[var(--color-ink-muted)]">
        A project keeps every version of one song together. Each version stores the exact settings it ran
        with, so an older take never changes when you regenerate.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-ink-faint)]" />
          <Input
            placeholder="Search projects by name, style or tag"
            aria-label="Search projects"
            className="pl-9"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {search ? (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-[var(--radius-sm)] text-[var(--color-ink-faint)] hover:bg-[var(--color-surface-2)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
        <Select value={sort} onValueChange={(value) => setSort(value as Sort)}>
          <SelectTrigger className="sm:w-52" aria-label="Sort projects">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORTS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <Skeleton key={index} className="h-28 w-full" />
          ))}
        </div>
      ) : items.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<FolderOpen className="h-6 w-6" />}
          title={search ? "No projects match that search" : "No projects yet"}
          description={
            search
              ? "Try a different name, style or tag."
              : "A project is created the first time you generate. Every later version of that song is kept in it."
          }
          action={
            search ? (
              <Button variant="surface" size="sm" onClick={() => setSearch("")}>
                Clear search
              </Button>
            ) : (
              <Button variant="primary" size="sm" asChild>
                <Link href="/create">Create the first one</Link>
              </Button>
            )
          }
        />
      )}
    </div>
  );
}
