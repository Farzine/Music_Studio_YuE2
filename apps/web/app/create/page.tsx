"use client";

import { Library } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { CreateForm } from "@/features/create/create-form";
import { GenerationCard } from "@/components/library/generation-card";
import { useGeneration, useGenerations, useProject, useProjectConfig } from "@/hooks/use-queries";
import { ApiRequestError } from "@/lib/api";
import type { ConfigObject } from "@/lib/config";

/**
 * The Create screen, in one of three states.
 *
 * Plain: a new song from the studio defaults.
 * `?from=<generation>`: regenerating — that take's exact settings are loaded
 * and every one of them stays editable. The take itself is never modified; a
 * new version is created when the form is submitted.
 * `?project=<project>`: a new version of a project, starting from the settings
 * saved on it.
 */
function CreateScreen() {
  const search = useSearchParams();
  const from = search.get("from") ?? undefined;
  const projectParam = search.get("project") ?? undefined;

  const source = useGeneration(from);
  const projectId = projectParam ?? source.data?.generation.project_id;
  const project = useProject(projectParam);
  const projectConfig = useProjectConfig(projectParam);

  // Wait for whichever source was asked for before mounting the form, so it is
  // never initialised from defaults and then silently re-seeded underneath the
  // user's first keystroke.
  if (from) {
    if (source.isLoading) return <FormSkeleton />;
    if (source.error) {
      return (
        <ErrorNotice
          title="Version unavailable"
          message={
            source.error instanceof ApiRequestError
              ? source.error.message
              : "That version could not be loaded, so its settings cannot be restored."
          }
          actions={
            <Button variant="surface" size="sm" asChild>
              <Link href="/create">Start from the defaults</Link>
            </Button>
          }
        />
      );
    }
  }
  if (projectParam) {
    if (project.isLoading || projectConfig.isLoading) return <FormSkeleton />;
    if (project.error || projectConfig.error) {
      const failure = project.error ?? projectConfig.error;
      return (
        <ErrorNotice
          title="Project unavailable"
          message={
            failure instanceof ApiRequestError
              ? failure.message
              : "That project could not be loaded, so its settings cannot be restored."
          }
          actions={
            <Button variant="surface" size="sm" asChild>
              <Link href="/create">Start from the defaults</Link>
            </Button>
          }
        />
      );
    }
  }

  const job = source.data?.generation;
  const initialConfig = (job?.config ?? projectConfig.data?.config) as ConfigObject | undefined;
  const origin = job
    ? {
        title: `Regenerating version ${job.version}${job.title ? ` of “${job.title}”` : ""}`,
        description:
          "Every setting that version ran with is loaded below and can be changed. Generating creates a " +
          "new version in the same project; version " +
          job.version +
          " is kept exactly as it is.",
        href: `/generations/${job.id}`,
        linkLabel: "Open original",
      }
    : projectParam && project.data
      ? {
          title: `New version of “${project.data.project.title || "Untitled project"}”`,
          description:
            projectConfig.data?.source === "defaults"
              ? "This project has no saved settings yet, so the studio defaults are loaded."
              : "The project's saved settings are loaded below. Change anything you like before generating.",
          href: `/projects/${project.data.project.id}`,
          linkLabel: "Open project",
        }
      : undefined;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="min-w-0">
        <CreateForm
          // Remounts when the source changes, so the loaded settings are the
          // ones that belong to it rather than a half-updated mixture.
          key={from ?? projectParam ?? "new"}
          initialConfig={initialConfig}
          initialTitle={job?.title ?? project.data?.project.title ?? ""}
          projectId={projectId}
          parentGenerationId={job?.id}
          origin={origin}
        />
      </div>

      <RecentColumn projectId={projectId} />
    </div>
  );
}

function RecentColumn({ projectId }: { projectId?: string }) {
  const { data, isLoading } = useGenerations({ limit: 12, project_id: projectId });

  return (
    <aside className="min-w-0 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          {projectId ? "Versions in this project" : "Recent generations"}
        </h2>
        <Button variant="ghost" size="sm" asChild>
          <Link href={projectId ? `/projects/${projectId}` : "/library"}>
            <Library className="h-3.5 w-3.5" />
            {projectId ? "History" : "Library"}
          </Link>
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} className="h-28 w-full" />
          ))}
        </div>
      ) : data && data.items.length > 0 ? (
        <div className="space-y-3">
          {data.items.map((job) => (
            <GenerationCard key={job.id} job={job} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="Nothing here yet"
          description="Describe a style, write a few lines, and press Create. Your songs will appear here."
        />
      )}
    </aside>
  );
}

function FormSkeleton() {
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="space-y-4">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

export default function CreatePage() {
  // useSearchParams needs a Suspense boundary in the app router.
  return (
    <React.Suspense fallback={<FormSkeleton />}>
      <CreateScreen />
    </React.Suspense>
  );
}
