"use client";

import { GitBranch, Sliders, Sparkles, Wand2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { type UploadedAudio } from "@/components/audio/audio-uploader";
import { BudgetPanel } from "@/components/generation/budget-panel";
import { PromptFields } from "@/components/generation/prompt-fields";
import { AdvancedSettings } from "@/components/settings/advanced-settings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, SectionHeading } from "@/components/ui/card";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { PresetPicker } from "@/features/create/preset-picker";
import { useBudgetEstimate } from "@/hooks/use-budget";
import { useCapabilities, useGenerationActions, usePresets, useSchema } from "@/hooks/use-queries";
import { ApiRequestError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { deepMerge, getPath, setPath, type ConfigObject } from "@/lib/config";
import type { Preset } from "@/types/api";

export function CreateForm({
  initialConfig,
  projectId,
  parentGenerationId,
  initialTitle = "",
  origin,
}: {
  initialConfig?: ConfigObject;
  /** Attach the new take to this project instead of creating a new one. */
  projectId?: string;
  /** The take this one was started from, recorded as lineage only. */
  parentGenerationId?: string;
  initialTitle?: string;
  /** Shown at the top so it is obvious where the loaded settings came from. */
  origin?: { title: string; description: string; href?: string; linkLabel?: string };
}) {
  const router = useRouter();
  const { data: schema, isLoading: schemaLoading } = useSchema();
  const { data: capabilities } = useCapabilities();
  const { data: presetData, refetch: refetchPresets } = usePresets();
  const { create } = useGenerationActions();

  const [config, setConfig] = React.useState<ConfigObject>(initialConfig ?? {});
  const [title, setTitle] = React.useState(initialTitle);
  // A loaded configuration is not a preset; showing one selected would claim
  // the settings came from somewhere they did not.
  const [activePreset, setActivePreset] = React.useState<string | null>(
    initialConfig ? null : "preset_balanced",
  );
  const [reference, setReference] = React.useState<UploadedAudio | null>(null);
  const [error, setError] = React.useState<ApiRequestError | null>(null);
  const [vramWarning, setVramWarning] = React.useState<string | null>(null);

  const defaults = presetData?.defaults as ConfigObject | undefined;
  const effective = React.useMemo<ConfigObject>(
    () => (defaults ? deepMerge(defaults, config) : config),
    [defaults, config],
  );

  const mode = (getPath(effective, "prompt.mode") as string) ?? "full";
  const style = (getPath(effective, "prompt.style") as string) ?? "";
  const lyrics = (getPath(effective, "prompt.lyrics") as string) ?? "";
  const duration = (getPath(effective, "sampling.max_duration_seconds") as number) ?? 360;
  const decoderMode = (getPath(effective, "decoder.mode") as string) ?? "tiled";
  const budget = (getPath(effective, "model.memory_budget_gib") as number) ?? 40;

  // Live token budget for exactly what would be submitted. The backend counts
  // with the checkpoint's own tokenizer, so the figures are the model's, not a
  // frontend approximation.
  const { data: tokenBudget } = useBudgetEstimate(effective, Boolean(defaults));
  const estimate = tokenBudget?.estimate;
  const overBudget = estimate?.risk === "UNSAFE";

  const update = (path: string, value: unknown) => {
    setConfig((current) => setPath(current, path, value));
    setActivePreset(null);
  };

  // Switching away from Cover drops the reference, so the request never
  // carries an input the chosen mode does not use.
  React.useEffect(() => {
    if (mode !== "cover" && getPath(effective, "prompt.reference_upload_id")) {
      setConfig((current) => setPath(current, "prompt.reference_upload_id", null));
      setReference(null);
    }
  }, [mode, effective]);

  React.useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const result = await api.vramEstimate(duration, decoderMode, budget);
        if (!cancelled) setVramWarning(result.warning?.message ?? null);
      } catch {
        if (!cancelled) setVramWarning(null);
      }
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [duration, decoderMode, budget]);

  const needsLyrics = mode !== "off";
  const needsReference = mode === "cover";
  const canSubmit =
    style.trim().length > 0 &&
    (!needsLyrics || lyrics.trim().length > 0) &&
    (!needsReference || Boolean(reference)) &&
    !overBudget;

  const blocker = !style.trim()
    ? "Describe a style to get started."
    : needsLyrics && !lyrics.trim()
      ? "Add lyrics, or switch to Direct Audio."
      : needsReference && !reference
        ? "Upload the recording you want to cover."
        : overBudget
          ? "This request does not fit the model's context window. Adjust it above."
          : null;

  const submit = async () => {
    setError(null);
    try {
      const result = await create.mutateAsync({
        title: title.trim() || undefined,
        project_id: projectId ?? null,
        parent_generation_id: parentGenerationId ?? null,
        // The whole configuration is sent, not a diff: the take that comes out
        // has to record exactly what it ran with.
        config: effective as Record<string, unknown>,
      });
      router.push(`/generations/${result.generation.id}`);
    } catch (submitError) {
      if (submitError instanceof ApiRequestError) {
        setError(submitError);
        return;
      }
      throw submitError;
    }
  };

  if (schemaLoading || !schema || !defaults) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-24 lg:pb-0">
      {origin ? (
        <div className="flex flex-wrap items-start gap-3 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-surface-2)] px-4 py-3">
          <GitBranch className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-accent)]" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{origin.title}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-[var(--color-ink-muted)]">
              {origin.description}
            </p>
          </div>
          {origin.href ? (
            <Button variant="ghost" size="xs" asChild>
              <Link href={origin.href}>{origin.linkLabel ?? "Open"}</Link>
            </Button>
          ) : null}
        </div>
      ) : null}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--color-accent)]" />
            {projectId ? "New version" : "Create music"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <Field
            label="Title"
            htmlFor="title"
            description={
              projectId
                ? "Names this version and its downloads. The project keeps its own name."
                : "Optional. Names the project and your downloads."
            }
          >
            <Input
              id="title"
              placeholder="Untitled"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>

          <PromptFields
            schema={schema}
            config={effective}
            capabilities={capabilities}
            reference={reference}
            onReferenceChange={setReference}
            onChange={update}
          />

          {estimate ? (
            <BudgetPanel
              estimate={estimate}
              limits={tokenBudget?.limits}
              onAdjust={(seconds) => update("sampling.max_duration_seconds", seconds)}
            />
          ) : null}

          {vramWarning ? <WarningNotice>{vramWarning}</WarningNotice> : null}
          {error ? (
            <ErrorNotice
              title={error.code.replace(/_/g, " ").toLowerCase()}
              message={error.message}
              guidance={error.guidance}
            />
          ) : null}

          {/* Desktop action. On phones the sticky bar below takes over. */}
          <div className="hidden lg:block">
            <Button
              variant="primary"
              size="lg"
              className="w-full"
              disabled={!canSubmit}
              loading={create.isPending}
              onClick={submit}
            >
              {create.isPending ? null : <Wand2 className="h-4 w-4" />}
              {create.isPending ? "Queueing…" : projectId ? "Generate new version" : "Create"}
            </Button>
            {blocker ? (
              <p className="mt-2 text-center text-xs text-[var(--color-ink-faint)]">{blocker}</p>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="gap-3 pb-3">
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
          <PresetPicker
            presets={(presetData?.items ?? []) as Preset[]}
            activeId={activePreset}
            currentConfig={config}
            onSaved={() => void refetchPresets()}
            onApply={(preset) => {
              // A preset is a full configuration, but it is a settings preset:
              // applying one must not wipe the song the user has written.
              const { prompt: _ignored, ...settings } = preset.config as unknown as ConfigObject;
              setConfig((current) => ({ ...settings, prompt: current.prompt }));
              setActivePreset(preset.id);
            }}
            onReset={() => {
              // Same rule in reverse: reset the settings, keep the song.
              setConfig((current) => (current.prompt ? { prompt: current.prompt } : {}));
              setActivePreset("preset_balanced");
            }}
          />
        </CardHeader>
        <CardContent>
          <AdvancedSettings
            schema={schema}
            config={effective}
            defaults={defaults}
            onChange={(next) => {
              setConfig(next);
              setActivePreset(null);
            }}
          />
        </CardContent>
      </Card>

      {/* Sticky create bar: on a phone the button must always be reachable. */}
      <div className="fixed inset-x-0 bottom-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom))] z-20 border-t border-[var(--color-line)] bg-[color-mix(in_oklch,var(--color-canvas)_94%,transparent)] px-4 py-3 backdrop-blur-xl lg:hidden">
        <Button
          variant="primary"
          size="lg"
          className="w-full"
          disabled={!canSubmit}
          loading={create.isPending}
          onClick={submit}
        >
          {create.isPending ? null : <Wand2 className="h-4 w-4" />}
          {create.isPending ? "Queueing…" : projectId ? "Generate new version" : "Create"}
        </Button>
        {blocker ? (
          <p className={cn("mt-1.5 text-center text-xs text-[var(--color-ink-faint)]")}>{blocker}</p>
        ) : null}
      </div>
    </div>
  );
}
