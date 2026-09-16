"use client";

import { LayoutGrid, Library as LibraryIcon, List, Search, SlidersHorizontal, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { GenerationCard } from "@/components/library/generation-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/controls";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { Input } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-media-query";
import { useGenerations, useSchema } from "@/hooks/use-queries";
import { cn } from "@/lib/cn";
import type { GenerationJob } from "@/types/api";

type View = "recent" | "favorites" | "failed" | "scores";
type Sort = "newest" | "oldest" | "longest" | "shortest" | "title";

const VIEWS: Record<View, { label: string; params: Record<string, string | boolean | undefined> }> = {
  recent: { label: "Recent", params: {} },
  favorites: { label: "Favourites", params: { favorite: true } },
  failed: { label: "Failed", params: { status: "FAILED" } },
  scores: { label: "Scores", params: {} },
};

const SORTS: { value: Sort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "longest", label: "Longest" },
  { value: "shortest", label: "Shortest" },
  { value: "title", label: "Title A–Z" },
];

function duration(job: GenerationJob): number {
  return job.artifacts.find((artifact) => artifact.kind === "audio")?.duration_seconds ?? 0;
}

export default function LibraryPage() {
  const isMobile = useIsMobile();
  const [view, setView] = React.useState<View>("recent");
  const [layout, setLayout] = React.useState<"list" | "grid">("list");
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [mode, setMode] = React.useState("");
  const [sort, setSort] = React.useState<Sort>("newest");
  const [filtersOpen, setFiltersOpen] = React.useState(false);
  const { data: schema } = useSchema();

  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const { data, isLoading } = useGenerations({
    ...VIEWS[view].params,
    search: debounced || undefined,
    mode: mode || undefined,
    limit: 200,
  });

  const items = React.useMemo(() => {
    let all = [...(data?.items ?? [])];
    if (view === "scores") {
      all = all.filter((job) => job.artifacts.some((artifact) => artifact.kind === "score"));
    }
    const sorters: Record<Sort, (a: GenerationJob, b: GenerationJob) => number> = {
      newest: (a, b) => b.requested_at.localeCompare(a.requested_at),
      oldest: (a, b) => a.requested_at.localeCompare(b.requested_at),
      longest: (a, b) => duration(b) - duration(a),
      shortest: (a, b) => duration(a) - duration(b),
      title: (a, b) => (a.title || "Untitled").localeCompare(b.title || "Untitled"),
    };
    return all.sort(sorters[sort]);
  }, [data, view, sort]);

  const modeOptions = schema?.parameters.find((parameter) => parameter.key === "prompt.mode")?.options ?? [];
  const filtered = Boolean(debounced || mode);

  const filterControls = (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <Select value={mode || "all"} onValueChange={(value) => setMode(value === "all" ? "" : value)}>
        <SelectTrigger className="sm:w-44" aria-label="Filter by mode">
          <SelectValue placeholder="Any mode" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Any mode</SelectItem>
          {modeOptions.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={sort} onValueChange={(value) => setSort(value as Sort)}>
        <SelectTrigger className="sm:w-44" aria-label="Sort">
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
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-semibold tracking-tight">Library</h1>
          <span className="text-sm text-[var(--color-ink-faint)]">
            {isLoading ? "…" : `${items.length} of ${data?.total ?? 0}`}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden rounded-[var(--radius-md)] border border-[var(--color-line)] p-1 sm:flex">
            <button
              type="button"
              aria-label="List view"
              aria-pressed={layout === "list"}
              onClick={() => setLayout("list")}
              className={cn(
                "grid h-8 w-8 place-items-center rounded-[var(--radius-sm)] transition-colors",
                layout === "list" ? "bg-[var(--color-surface-3)] text-[var(--color-ink)]" : "text-[var(--color-ink-faint)]",
              )}
            >
              <List className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label="Grid view"
              aria-pressed={layout === "grid"}
              onClick={() => setLayout("grid")}
              className={cn(
                "grid h-8 w-8 place-items-center rounded-[var(--radius-sm)] transition-colors",
                layout === "grid" ? "bg-[var(--color-surface-3)] text-[var(--color-ink)]" : "text-[var(--color-ink-faint)]",
              )}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
          </div>
          {isMobile ? (
            <Button variant="surface" size="icon" aria-label="Filters" onClick={() => setFiltersOpen(true)}>
              <SlidersHorizontal className="h-4 w-4" />
            </Button>
          ) : null}
        </div>
      </div>

      <div className="scroll-x -mx-4 px-4 sm:mx-0 sm:px-0">
        <Tabs value={view} onValueChange={(value) => setView(value as View)}>
          <TabsList>
            {(Object.keys(VIEWS) as View[]).map((key) => (
              <TabsTrigger key={key} value={key}>
                {VIEWS[key].label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-ink-faint)]" />
          <Input
            placeholder="Search title, style or lyrics"
            className="pl-9"
            aria-label="Search generations"
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
        <div className="hidden sm:block">{filterControls}</div>
      </div>

      {filtered ? (
        <div className="flex flex-wrap items-center gap-2">
          {debounced ? <Badge tone="accent">search: {debounced}</Badge> : null}
          {mode ? <Badge tone="accent">mode: {mode}</Badge> : null}
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              setSearch("");
              setMode("");
            }}
          >
            Clear
          </Button>
        </div>
      ) : null}

      {isLoading ? (
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="h-32 w-full" />
          ))}
        </div>
      ) : items.length > 0 ? (
        <div
          className={cn(
            "grid gap-3",
            layout === "grid"
              ? "sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
              : "lg:grid-cols-2 2xl:grid-cols-3",
          )}
        >
          {items.map((job) => (
            <GenerationCard key={job.id} job={job} layout={layout} />
          ))}
        </div>
      ) : (
        <Card className="border-none bg-transparent">
          <EmptyState
            icon={<LibraryIcon className="h-6 w-6" />}
            title={filtered ? "No matches" : view === "recent" ? "Your library is empty" : `Nothing in ${VIEWS[view].label.toLowerCase()}`}
            description={
              filtered
                ? "Try a different search, or clear the filters."
                : "Everything you generate is stored locally under the data directory and shows up here."
            }
            action={
              filtered ? (
                <Button
                  variant="surface"
                  size="sm"
                  onClick={() => {
                    setSearch("");
                    setMode("");
                  }}
                >
                  Clear filters
                </Button>
              ) : (
                <Button variant="primary" size="sm" asChild>
                  <Link href="/create">Create music</Link>
                </Button>
              )
            }
          />
        </Card>
      )}

      <Sheet open={filtersOpen} onOpenChange={setFiltersOpen} title="Filters">
        <div className="space-y-4 pb-4">{filterControls}</div>
      </Sheet>
    </div>
  );
}
