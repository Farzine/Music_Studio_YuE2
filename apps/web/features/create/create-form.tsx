"use client";

import { Dice5, Loader2, Music4, Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { FieldShell, Input, Textarea } from "@/components/ui/field";
import { AdvancedSettings } from "@/features/create/advanced-settings";
import { PresetPicker } from "@/features/create/preset-picker";
import { ReferenceAudioPanel, type ReferenceAudio } from "@/features/create/reference-audio";
import { useCapabilities, useGenerationActions, usePresets, useSchema } from "@/hooks/use-queries";
import { ApiRequestError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { SECTION_TAGS, STYLE_EXAMPLES, getPath, setPath, type ConfigObject } from "@/lib/config";
import { formatDuration } from "@/lib/format";
import type { GenerationMode, ParameterOption, Preset } from "@/types/api";

const MODE_ICON: Record<string, string> = {
  full: "Full Song",
  melody: "Melody Guided",
  off: "Direct Audio",
  cover: "Cover",
  score_edit: "Score Edit",
};

export function CreateForm({ initialConfig }: { initialConfig?: ConfigObject }) {
  const router = useRouter();
  const { data: schema, isLoading: schemaLoading } = useSchema();
  const { data: capabilities } = useCapabilities();
  const { data: presetData, refetch: refetchPresets } = usePresets();
  const { create } = useGenerationActions();

  const [config, setConfig] = React.useState<ConfigObject>(initialConfig ?? {});
  const [title, setTitle] = React.useState("");
  const [activePreset, setActivePreset] = React.useState<string | null>("preset_balanced");
  const [reference, setReference] = React.useState<ReferenceAudio | null>(null);
  const [error, setError] = React.useState<ApiRequestError | null>(null);
  const [vramWarning, setVramWarning] = React.useState<string | null>(null);

  const defaults = presetData?.defaults as ConfigObject | undefined;
  const effective = React.useMemo<ConfigObject>(() => {
    if (!defaults) return config;
    return mergeDeep(defaults, config);
  }, [defaults, config]);

  const modeParameter = schema?.parameters.find((parameter) => parameter.key === "prompt.mode");
  const mode = (getPath(effective, "prompt.mode") as GenerationMode) ?? "full";
  const style = (getPath(effective, "prompt.style") as string) ?? "";
  const lyrics = (getPath(effective, "prompt.lyrics") as string) ?? "";
  const duration = (getPath(effective, "sampling.max_duration_seconds") as number) ?? 360;
  const seed = getPath(effective, "sampling.seed") as number | undefined;
  const decoderMode = (getPath(effective, "decoder.mode") as string) ?? "tiled";
  const budget = (getPath(effective, "model.memory_budget_gib") as number) ?? 40;
  const coverCapability = capabilities?.capabilities?.cover;

  const update = (path: string, value: unknown) => {
    setConfig((current) => setPath(current, path, value));
    setActivePreset(null);
  };

  // Ask the backend whether this request looks too large before it is queued.
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
    const next = lyrics ? `${lyrics.replace(/\s*$/, "")}\n\n${tag}\n` : `${tag}\n`;
    update("prompt.lyrics", next);
  };

  const submit = async () => {
    setError(null);
    try {
      const payload = { ...config } as ConfigObject;
      const result = await create.mutateAsync({
        title: title.trim() || undefined,
        config: payload as Record<string, unknown>,
      });
      router.push(`/generations/${result.generation.id}`);
    } catch (submitError) {
      setError(submitError instanceof ApiRequestError ? submitError : null);
      if (!(submitError instanceof ApiRequestError)) throw submitError;
    }
  };

  if (schemaLoading || !schema || !defaults) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const modeOptions = (modeParameter?.options ?? []) as ParameterOption[];
  const canSubmit = style.trim().length > 0 && (mode === "off" || lyrics.trim().length > 0);

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <Music4 className="h-4 w-4 text-[var(--color-accent)]" />
            Create music
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <FieldShell label="Title" help="Optional. Used to name the project and downloads." htmlFor="title">
            <Input
              id="title"
              placeholder="Untitled"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </FieldShell>

          <FieldShell label="Mode" help="Choose how much of the composition the model plans before it sings.">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {modeOptions.map((option) => {
                const disabled = option.enabled === false;
                const selected = option.value === mode;
                return (
                  <button
                    key={option.value}
                    type="button"
                    disabled={disabled}
                    title={disabled ? option.disabled_reason : option.help}
                    onClick={() => update("prompt.mode", option.value)}
                    className={cn(
                      "rounded-xl border px-3 py-2.5 text-left text-xs transition-colors",
                      selected
                        ? "border-[var(--color-accent)] bg-[color-mix(in_oklch,var(--color-accent)_12%,transparent)]"
                        : "border-[var(--color-line)] hover:border-[var(--color-ink-faint)]",
                      disabled && "cursor-not-allowed opacity-45",
                    )}
                  >
                    <span className="block font-medium">{MODE_ICON[option.value] ?? option.label}</span>
                    <span className="mt-0.5 block leading-snug text-[var(--color-ink-faint)]">
                      {disabled ? option.disabled_reason : option.help}
                    </span>
                  </button>
                );
              })}
            </div>
          </FieldShell>

          <FieldShell
            label="Style"
            help="Genre, instruments, vocal character, language and tempo."
            htmlFor="style"
            hint={<span>{style.length}/4000</span>}
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
                  className="rounded-lg border border-[var(--color-line)] px-2 py-1 text-[11px] text-[var(--color-ink-faint)] transition-colors hover:border-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
                >
                  {example.split(",")[0]}
                </button>
              ))}
            </div>
          </FieldShell>

          <FieldShell
            label="Lyrics"
            help={
              mode === "off"
                ? "Direct Audio ignores lyrics; leave this empty for an instrumental idea."
                : "Use section tags on their own line."
            }
            htmlFor="lyrics"
            hint={<span>{lyrics.length}/20000</span>}
          >
            <div className="mb-1.5 flex flex-wrap gap-1.5">
              {SECTION_TAGS.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => insertTag(tag)}
                  className="rounded-lg border border-[var(--color-line)] px-2 py-1 font-mono text-[11px] text-[var(--color-ink-muted)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                >
                  {tag}
                </button>
              ))}
            </div>
            <Textarea
              id="lyrics"
              rows={12}
              placeholder={"[Verse]\nNeon fades along the lane\n\n[Chorus]\nLet the day come into view"}
              value={lyrics}
              onChange={(event) => update("prompt.lyrics", event.target.value)}
              className="font-mono text-[13px]"
            />
          </FieldShell>

          <div className="grid gap-4 sm:grid-cols-2">
            <FieldShell
              label="Maximum duration"
              help="The model stops when the song is finished; this is only a ceiling."
              hint={<span>{formatDuration(duration)}</span>}
            >
              <input
                type="range"
                min={8}
                max={960}
                step={1}
                value={duration}
                onChange={(event) => update("sampling.max_duration_seconds", Number(event.target.value))}
                className="w-full accent-[var(--color-accent)]"
                aria-label="Maximum duration"
              />
              <p className="text-xs text-[var(--color-ink-faint)]">
                {Math.round(duration * 25).toLocaleString()} acoustic tokens at 25 per second
              </p>
            </FieldShell>

            <FieldShell label="Seed" help="The same seed, settings and weights reproduce a generation." htmlFor="seed">
              <div className="flex gap-2">
                <Input
                  id="seed"
                  type="number"
                  value={seed ?? ""}
                  onChange={(event) => update("sampling.seed", Number(event.target.value))}
                />
                <Button
                  variant="surface"
                  size="icon"
                  aria-label="Randomise the seed"
                  onClick={() => update("sampling.control_after_generate", "randomize")}
                >
                  <Dice5 className="h-4 w-4" />
                </Button>
              </div>
              <p className="text-xs text-[var(--color-ink-faint)]">
                {getPath(effective, "sampling.control_after_generate") === "randomize"
                  ? "A new seed is drawn on the server and saved to the manifest."
                  : "Fixed seed."}
              </p>
            </FieldShell>
          </div>

          {mode === "cover" ? (
            <FieldShell label="Reference audio" help="Transcribed to a melody score, then used to condition generation.">
              <ReferenceAudioPanel
                enabled={Boolean(coverCapability?.supported)}
                disabledReason={coverCapability?.reason}
                value={reference}
                onChange={setReference}
              />
            </FieldShell>
          ) : null}

          {vramWarning ? <WarningNotice>{vramWarning}</WarningNotice> : null}
          {error ? (
            <ErrorNotice title={error.code} message={error.message} guidance={error.guidance} />
          ) : null}

          <Button
            variant="primary"
            size="lg"
            className="w-full"
            disabled={!canSubmit || create.isPending}
            onClick={submit}
          >
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            {create.isPending ? "Queueing…" : "Create"}
          </Button>
          {!canSubmit ? (
            <p className="text-center text-xs text-[var(--color-ink-faint)]">
              {style.trim() ? "Add lyrics, or switch to Direct Audio." : "Describe a style to get started."}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center justify-between">
            <span>Advanced settings</span>
            <Badge tone="neutral">{schema.backend}</Badge>
          </CardTitle>
          <PresetPicker
            presets={(presetData?.items ?? []) as Preset[]}
            activeId={activePreset}
            currentConfig={config}
            onSaved={() => void refetchPresets()}
            onApply={(preset) => {
              setConfig(preset.config as unknown as ConfigObject);
              setActivePreset(preset.id);
            }}
            onReset={() => {
              setConfig({});
              setActivePreset("preset_balanced");
            }}
          />
        </CardHeader>
        <CardContent>
          <AdvancedSettings
            schema={schema}
            config={effective}
            onChange={(next) => {
              setConfig(next);
              setActivePreset(null);
            }}
          />
        </CardContent>
      </Card>
    </div>
  );
}

function mergeDeep(base: ConfigObject, overrides: ConfigObject): ConfigObject {
  const result: ConfigObject = { ...base };
  Object.entries(overrides).forEach(([key, value]) => {
    const existing = result[key];
    if (value && typeof value === "object" && !Array.isArray(value) && existing && typeof existing === "object") {
      result[key] = mergeDeep(existing as ConfigObject, value as ConfigObject);
    } else {
      result[key] = value;
    }
  });
  return result;
}
