"use client";

import { Dice5 } from "lucide-react";
import * as React from "react";

import { AudioUploader, type UploadedAudio } from "@/components/audio/audio-uploader";
import { ModeSelector } from "@/components/generation/mode-selector";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/controls";
import { Field, Input, Textarea } from "@/components/ui/field";
import { formatDuration } from "@/lib/format";
import { SECTION_TAGS, STYLE_EXAMPLES, getPath, type ConfigObject } from "@/lib/config";
import type { Capabilities, GenerationSchema } from "@/types/api";

/**
 * The song itself: style, lyrics, mode, reference audio, length and seed.
 *
 * Shared by the Create screen and a project's settings editor so the two
 * cannot drift apart. Everything below this in the form comes from the backend
 * schema instead, through AdvancedSettings.
 */
export function PromptFields({
  schema,
  config,
  capabilities,
  reference,
  onReferenceChange,
  onChange,
}: {
  schema: GenerationSchema;
  config: ConfigObject;
  capabilities?: Capabilities;
  reference: UploadedAudio | null;
  onReferenceChange: (next: UploadedAudio | null) => void;
  onChange: (path: string, value: unknown) => void;
}) {
  const parameter = (key: string) => schema.parameters.find((item) => item.key === key);
  const mode = (getPath(config, "prompt.mode") as string) ?? "full";
  const style = (getPath(config, "prompt.style") as string) ?? "";
  const lyrics = (getPath(config, "prompt.lyrics") as string) ?? "";
  const duration = (getPath(config, "sampling.max_duration_seconds") as number) ?? 360;
  const seed = getPath(config, "sampling.seed") as number | undefined;
  const seedBehaviour = getPath(config, "sampling.control_after_generate") as string;
  const cover = capabilities?.capabilities?.cover;
  const needsLyrics = mode !== "off";

  const insertTag = (tag: string) =>
    onChange("prompt.lyrics", lyrics ? `${lyrics.replace(/\s*$/, "")}\n\n${tag}\n` : `${tag}\n`);

  return (
    <>
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
          onChange={(event) => onChange("prompt.style", event.target.value)}
        />
        <div className="flex flex-wrap gap-1.5">
          {STYLE_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => onChange("prompt.style", example)}
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
          onChange={(event) => onChange("prompt.lyrics", event.target.value)}
          className="font-mono text-[13px]"
        />
      </Field>

      <ModeSelector
        parameter={parameter("prompt.mode")}
        value={mode}
        onChange={(next) => onChange("prompt.mode", next)}
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
              onReferenceChange(next);
              onChange("prompt.reference_upload_id", next?.id ?? null);
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
            onValueChange={([next]) => onChange("sampling.max_duration_seconds", next)}
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
              onChange={(event) => onChange("sampling.seed", Number(event.target.value))}
            />
            <Button
              variant={seedBehaviour === "randomize" ? "primary" : "surface"}
              size="icon"
              aria-label="Randomise the seed for each run"
              aria-pressed={seedBehaviour === "randomize"}
              onClick={() =>
                onChange(
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
    </>
  );
}
