"use client";

import { AudioLines, FileMusic, Music4, Radio, Waves } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Field } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useIsMobile } from "@/hooks/use-media-query";
import { cn } from "@/lib/cn";
import type { ParameterDefinition, ParameterOption } from "@/types/api";

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  full: Music4,
  melody: Waves,
  off: AudioLines,
  cover: Radio,
  score_edit: FileMusic,
};

/**
 * Generation mode as a set of cards on desktop, a select on phones.
 *
 * Availability comes from the backend capability document. An unavailable mode
 * stays visible with the reason attached, so it is clear the feature exists
 * and what it needs — not simply absent.
 */
export function ModeSelector({
  parameter,
  value,
  onChange,
}: {
  parameter?: ParameterDefinition;
  value: string;
  onChange: (value: string) => void;
}) {
  const isMobile = useIsMobile();
  const options = (parameter?.options ?? []) as ParameterOption[];
  if (options.length === 0) return null;

  if (isMobile) {
    return (
      <Field
        label="Mode"
        htmlFor="mode-selector"
        guidance={parameter?.guidance}
        description={options.find((option) => option.value === value)?.help}
      >
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger id="mode-selector">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem
                key={option.value}
                value={option.value}
                disabled={option.enabled === false}
                help={option.enabled === false ? option.disabled_reason : option.help}
              >
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
    );
  }

  return (
    <Field label="Mode" guidance={parameter?.guidance}>
      <div
        role="radiogroup"
        aria-label="Generation mode"
        className="grid grid-cols-2 gap-2 lg:grid-cols-3 xl:grid-cols-5"
      >
        {options.map((option) => {
          const Icon = ICONS[option.value] ?? Music4;
          const disabled = option.enabled === false;
          const selected = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-disabled={disabled}
              disabled={disabled}
              title={disabled ? option.disabled_reason : option.help}
              onClick={() => onChange(option.value)}
              className={cn(
                "group flex flex-col gap-2 rounded-[var(--radius-md)] border p-3 text-left transition-[border-color,background-color]",
                selected
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                  : "border-[var(--color-line)] hover:border-[var(--color-line-strong)] hover:bg-[var(--color-surface-2)]",
                disabled && "cursor-not-allowed opacity-50 hover:border-[var(--color-line)] hover:bg-transparent",
              )}
            >
              <span className="flex items-center gap-2">
                <Icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    selected ? "text-[var(--color-accent)]" : "text-[var(--color-ink-faint)]",
                  )}
                />
                <span className="truncate text-sm font-medium">{option.label}</span>
              </span>
              <span className="line-clamp-2 text-xs leading-snug text-[var(--color-ink-faint)]">
                {disabled ? option.disabled_reason : option.help}
              </span>
              {disabled ? <Badge tone="warn">unavailable</Badge> : null}
            </button>
          );
        })}
      </div>
    </Field>
  );
}
