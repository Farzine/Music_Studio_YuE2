"use client";

import { Dice5, Sliders, Sparkles, Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { AudioUploader, type UploadedAudio } from "@/components/audio/audio-uploader";
import { BudgetPanel } from "@/components/generation/budget-panel";
import { ModeSelector } from "@/components/generation/mode-selector";
import { AdvancedSettings } from "@/components/settings/advanced-settings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, SectionHeading } from "@/components/ui/card";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { Field, Input, Textarea } from "@/components/ui/field";
import { Slider } from "@/components/ui/controls";
import { PresetPicker } from "@/features/create/preset-picker";
import { useBudgetEstimate } from "@/hooks/use-budget";
import { useCapabilities, useGenerationActions, usePresets, useSchema } from "@/hooks/use-queries";
import { ApiRequestError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { SECTION_TAGS, STYLE_EXAMPLES, deepMerge, getPath, setPath, type ConfigObject } from "@/lib/config";
import { formatDuration } from "@/lib/format";
import type { Preset } from "@/types/api";

export function CreateForm({ initialConfig }: { initialConfig?: ConfigObject }) {
  const router = useRouter();
  const { data: schema, isLoading: schemaLoading } = useSchema();
  const { data: capabilities } = useCapabilities();
  const { data: presetData, refetch: refetchPresets } = usePresets();
  const { create } = useGenerationActions();

  const [config, setConfig] = React.useState<ConfigObject>(initialConfig ?? {});
  const [title, setTitle] = React.useState("");
  const [activePreset, setActivePreset] = React.useState<string | null>("preset_balanced");
  const [reference, setReference] = React.useState<UploadedAudio | null>(null);
  const [error, setError] = React.useState<ApiRequestError | null>(null);
  const [vramWarning, setVramWarning] = React.useState<string | null>(null);

  const defaults = presetData?.defaults as ConfigObject | undefined;
  const effective = React.useMemo<ConfigObject>(
    () => (defaults ? deepMerge(defaults, config) : config),
    [defaults, config],
  );

  const parameter = (key: string) => schema?.parameters.find((item) => item.key === key);
  const mode = (getPath(effective, "prompt.mode") as string) ?? "full";
  const style = (getPath(effective, "prompt.style") as string) ?? "";
  const lyrics = (getPath(effective, "prompt.lyrics") as string) ?? "";
  const duration = (getPath(effective, "sampling.max_duration_seconds") as number) ?? 360;
  const seed = getPath(effective, "sampling.seed") as number | undefined;
  const seedBehaviour = getPath(effective, "sampling.control_after_generate") as string;
  const decoderMode = (getPath(effective, "decoder.mode") as string) ?? "tiled";
  const budget = (getPath(effective, "model.memory_budget_gib") as number) ?? 40;
  const cover = capabilities?.capabilities?.cover;

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

  const insertTag = (tag: string) => {
    update("prompt.lyrics", lyrics ? `${lyrics.replace(/\s*$/, "")}\n\n${tag}\n` : `${tag}\n`);
  };

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
        config: config as Record<string, unknown>,
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
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--color-accent)]" />
            Create music
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <Field label="Title" description="Optional. Names the project and your downloads." htmlFor="title">
            <Input
              id="title"
              placeholder="Untitled"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>

          <Field
            label="Style"
            htmlFor="style"
            required
            guidance={parameter("prompt.style")?.guidance}
            description="Genre, instruments, vocal character, language and tempo."
            value={`${style.length}/4000`}
          >
            <Textarea
              id="style"
              rows={3}
              placeholder={STYLE_EXAMPLES[0]}
              value={style}
              onChange={(event) => update("prompt.style", event.target.value)}
            />
            <div className="flex flex-wrap gap-1.5">
              {STYLE_EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => update("prompt.style", example)}
                  className="rounded-[var(--radius-sm)] border border-[var(--color-line)] px-2 py-1 text-[11px] text-[var(--color-ink-faint)] transition-colors hover:border-[var(--color-line-strong)] hover:text-[var(--color-ink)]"
                >
                  {example.split(",")[0]}
                </button>
              ))}
            </div>
          </Field>

          <Field
            label="Lyrics"
            htmlFor="lyrics"
            required={needsLyrics}
            guidance={parameter("prompt.lyrics")?.guidance}
            description={
              needsLyrics
                ? "Use section tags on their own line."
                : "Direct Audio ignores lyrics — leave this empty for an instrumental."
            }
            value={`${lyrics.length}/20000`}
          >
            <div className="flex flex-wrap gap-1.5">
              {SECTION_TAGS.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => insertTag(tag)}
                  className="rounded-[var(--radius-sm)] border border-[var(--color-line)] px-2 py-1 font-mono text-[11px] text-[var(--color-ink-muted)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                >
                  {tag}
                </button>
              ))}
            </div>
            <Textarea
              id="lyrics"
              rows={11}
              placeholder={"[Verse]\nNeon fades along the lane\n\n[Chorus]\nLet the day come into view"}
              value={lyrics}
              onChange={(event) => update("prompt.lyrics", event.target.value)}
              className="font-mono text-[13px]"
            />
          </Field>

          <ModeSelector
            parameter={parameter("prompt.mode")}
            value={mode}
            onChange={(next) => update("prompt.mode", next)}
          />

          {mode === "cover" ? (
            <Field
              label="Reference audio"
              required
              guidance={parameter("prompt.reference_upload_id")?.guidance}
            >
              <AudioUploader
                value={reference}
                disabled={!cover?.supported}
                disabledReason={cover?.reason}
                onChange={(next) => {
                  setReference(next);
                  update("prompt.reference_upload_id", next?.id ?? null);
                }}
              />
            </Field>
          ) : null}

          <div className="grid gap-5 sm:grid-cols-2">
            <Field
              label="Maximum duration"
              guidance={parameter("sampling.max_duration_seconds")?.guidance}
              value={formatDuration(duration)}
              description={
                `${Math.round(duration * 25).toLocaleString()} acoustic tokens at 25 per second. ` +
                "The model decides how long the song is, so this is a hard stop rather than a target — " +
                "with “Let the song finish” on, it is raised if the planned song needs more."
              }
            >
              <Slider
                value={[duration]}
                min={8}
                max={960}
                step={1}
                aria-label="Maximum duration"
                onValueChange={([next]) => update("sampling.max_duration_seconds", next)}
              />
            </Field>

            <Field
              label="Seed"
              htmlFor="seed"
              guidance={parameter("sampling.seed")?.guidance}
              description={
                seedBehaviour === "randomize"
                  ? "A new seed is drawn on the server for each run and saved to the manifest."
                  : "The same seed, settings and weights reproduce this exact song."
              }
            >
              <div className="flex gap-2">
                <Input
                  id="seed"
                  type="number"
                  inputMode="numeric"
                  className="tabular-nums"
                  value={seed ?? ""}
                  onChange={(event) => update("sampling.seed", Number(event.target.value))}
                />
                <Button
                  variant={seedBehaviour === "randomize" ? "primary" : "surface"}
                  size="icon"
                  aria-label="Randomise the seed for each run"
                  aria-pressed={seedBehaviour === "randomize"}
                  onClick={() =>
                    update(
                      "sampling.control_after_generate",
                      seedBehaviour === "randomize" ? "fixed" : "randomize",
                    )
                  }
                >
                  <Dice5 className="h-4 w-4" />
                </Button>
              </div>
            </Field>
          </div>

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
              {create.isPending ? "Queueing…" : "Create"}
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
          {create.isPending ? "Queueing…" : "Create"}
        </Button>
        {blocker ? (
          <p className={cn("mt-1.5 text-center text-xs text-[var(--color-ink-faint)]")}>{blocker}</p>
        ) : null}
      </div>
    </div>
  );
}
