"use client";

import { ArrowLeft, Check, RotateCcw, Sliders, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";

import { type UploadedAudio } from "@/components/audio/audio-uploader";
import { BudgetPanel } from "@/components/generation/budget-panel";
import { PromptFields } from "@/components/generation/prompt-fields";
import { AdvancedSettings } from "@/components/settings/advanced-settings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, SectionHeading } from "@/components/ui/card";
import { ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { useBudgetEstimate } from "@/hooks/use-budget";
import {
  useCapabilities,
  usePresets,
  useProject,
  useProjectActions,
  useProjectConfig,
  useSchema,
} from "@/hooks/use-queries";
import { ApiRequestError } from "@/lib/api";
import { changedPaths, deepMerge, getPath, setPath, type ConfigObject } from "@/lib/config";

/**
 * A project's generation settings.
 *
 * What is edited here is the starting point for the project's *next* version.
 * Versions already generated keep the settings they ran with and are not
 * touched by anything on this page — that separation is the whole point of
 * storing a snapshot per generation.
 */
export default function ProjectSettingsPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = params?.id;

  const { data: project, isLoading: projectLoading } = useProject(projectId);
  const { data: loaded, isLoading: configLoading } = useProjectConfig(projectId);
  const { data: schema } = useSchema();
  const { data: capabilities } = useCapabilities();
  const { data: presetData } = usePresets();
  const { updateConfig } = useProjectActions();

  const [config, setConfig] = React.useState<ConfigObject | null>(null);
  const [reference, setReference] = React.useState<UploadedAudio | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);

  const starting = loaded?.config as ConfigObject | undefined;
  React.useEffect(() => {
    if (starting) setConfig(starting as ConfigObject);
  }, [starting]);

  const defaults = presetData?.defaults as ConfigObject | undefined;
  const effective = React.useMemo<ConfigObject>(
    () => (defaults && config ? deepMerge(defaults, config) : (config ?? {})),
    [defaults, config],
  );

  const { data: tokenBudget } = useBudgetEstimate(effective, Boolean(config));
  const dirty = React.useMemo(
    () => (starting && config ? changedPaths(starting, config).length > 0 : false),
    [starting, config],
  );

  const update = (path: string, value: unknown) => {
    setSaved(false);
    setConfig((current) => setPath(current ?? {}, path, value));
  };

  const save = async () => {
    if (!projectId || !config) return;
    setError(null);
    try {
      await updateConfig.mutateAsync({ id: projectId, config: effective as Record<string, unknown> });
      setSaved(true);
    } catch (saveError) {
      setError(
        saveError instanceof ApiRequestError ? saveError.message : "The settings could not be saved.",
      );
    }
  };

  const saveAndGenerate = async () => {
    await save();
    if (projectId) router.push(`/create?project=${projectId}`);
  };

  if (projectLoading || configLoading || !schema || !config || !defaults) {
    return <Skeleton className="h-96 w-full" />;
  }

  const style = (getPath(effective, "prompt.style") as string) ?? "";
  const canSave = style.trim().length > 0;

  return (
    <div className="space-y-5 pb-24 lg:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/projects/${projectId}`}>
            <ArrowLeft className="h-4 w-4" />
            Back to project
          </Link>
        </Button>
        <h1 className="min-w-0 flex-1 truncate text-xl font-semibold tracking-tight">
          {project?.project.title || "Untitled project"} · configuration
        </h1>
        {dirty ? <Badge tone="warn">unsaved changes</Badge> : null}
        {saved && !dirty ? (
          <Badge tone="accent">
            <Check className="h-3 w-3" />
            saved
          </Badge>
        ) : null}
      </div>

      <div className="rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-surface-2)] px-4 py-3 text-sm leading-relaxed text-[var(--color-ink-muted)]">
        These settings are where the project&apos;s next version starts from.{" "}
        {loaded?.source === "latest_generation"
          ? "They were loaded from the most recent version, because this project has none saved yet."
          : loaded?.source === "defaults"
            ? "The studio defaults are shown, because this project has neither saved settings nor a version yet."
            : "They are the project's own saved settings."}{" "}
        Saving never changes a version that has already been generated.
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--color-accent)]" />
            Song
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <PromptFields
            schema={schema}
            config={effective}
            capabilities={capabilities}
            reference={reference}
            onReferenceChange={setReference}
            onChange={update}
          />
          {tokenBudget?.estimate ? (
            <BudgetPanel
              estimate={tokenBudget.estimate}
              limits={tokenBudget.limits}
              onAdjust={(seconds) => update("sampling.max_duration_seconds", seconds)}
            />
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <SectionHeading
            title={
              <span className="flex items-center gap-2">
                <Sliders className="h-4 w-4 text-[var(--color-ink-faint)]" />
                Advanced settings
              </span>
            }
            description="Everything the backend supports. Hover or tap the ⓘ beside any setting for what it does."
            action={<Badge tone="outline">{schema.backend}</Badge>}
          />
        </CardHeader>
        <CardContent>
          <AdvancedSettings
            schema={schema}
            config={effective}
            defaults={defaults}
            onChange={(next) => {
              setSaved(false);
              setConfig(next);
            }}
          />
        </CardContent>
      </Card>

      {error ? <ErrorNotice title="Not saved" message={error} /> : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={save} disabled={!canSave} loading={updateConfig.isPending}>
          <Check className="h-4 w-4" />
          Save settings
        </Button>
        <Button variant="surface" onClick={saveAndGenerate} disabled={!canSave}>
          <Sparkles className="h-4 w-4" />
          Save and generate a new version
        </Button>
        <Button
          variant="ghost"
          disabled={!dirty}
          onClick={() => {
            setConfig(starting as ConfigObject);
            setSaved(false);
          }}
        >
          <RotateCcw className="h-4 w-4" />
          Discard changes
        </Button>
        {!canSave ? (
          <p className="text-xs text-[var(--color-ink-faint)]">A style description is required.</p>
        ) : null}
      </div>
    </div>
  );
}
