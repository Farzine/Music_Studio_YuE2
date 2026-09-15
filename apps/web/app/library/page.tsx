"use client";

import { Library as LibraryIcon, Search } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/controls";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { Input } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SongCard } from "@/features/library/song-card";
import { useGenerations, useSchema } from "@/hooks/use-queries";

type View = "recent" | "favorites" | "failed" | "scores";

const VIEW_PARAMS: Record<View, Record<string, string | boolean | undefined>> = {
  recent: {},
  favorites: { favorite: true },
  failed: { status: "FAILED" },
  scores: {},
};

export default function LibraryPage() {
  const [view, setView] = React.useState<View>("recent");
  const [search, setSearch] = React.useState("");
  const [mode, setMode] = React.useState<string>("");
  const [debounced, setDebounced] = React.useState("");
  const { data: schema } = useSchema();

  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const { data, isLoading } = useGenerations({
    ...VIEW_PARAMS[view],
    search: debounced || undefined,
    mode: mode || undefined,
    limit: 200,
  });

  const items = React.useMemo(() => {
    const all = data?.items ?? [];
    if (view === "scores") return all.filter((job) => job.artifacts.some((artifact) => artifact.kind === "score"));
    return all;
  }, [data, view]);

  const modeOptions = schema?.parameters.find((parameter) => parameter.key === "prompt.mode")?.options ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Library</h1>
        <span className="text-sm text-[var(--color-ink-faint)]">{data?.total ?? 0} generations</span>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Tabs value={view} onValueChange={(value) => setView(value as View)}>
          <TabsList>
            <TabsTrigger value="recent">Recent</TabsTrigger>
            <TabsTrigger value="favorites">Favourites</TabsTrigger>
            <TabsTrigger value="failed">Failed</TabsTrigger>
            <TabsTrigger value="scores">Saved scores</TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-ink-faint)]" />
          <Input
            placeholder="Search title, style or lyrics"
            className="pl-9"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        <div className="w-44">
          <Select value={mode} onValueChange={(value) => setMode(value === "all" ? "" : value)}>
            <SelectTrigger>
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
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="h-32 w-full" />
          ))}
        </div>
      ) : items.length > 0 ? (
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {items.map((job) => (
            <SongCard key={job.id} job={job} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<LibraryIcon className="h-6 w-6" />}
          title={debounced ? "No matches" : "Your library is empty"}
          description={
            debounced
              ? "Try a different search, or clear the filters."
              : "Everything you generate is stored locally under the data directory and shows up here."
          }
          action={
            debounced ? (
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
            ) : null
          }
        />
      )}
    </div>
  );
}
