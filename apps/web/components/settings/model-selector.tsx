"use client";

import { CircleAlert, HardDrive, Loader2 } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Field } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatBytes } from "@/lib/format";
import type { ParameterDefinition, ParameterOption } from "@/types/api";

/**
 * Model picker with the metadata the backend reports.
 *
 * The backend is the only source of truth about which models exist; nothing
 * here is hard-coded. Every state the selector can be in — loading, available,
 * none found, selected-but-unavailable — is handled explicitly and explained,
 * rather than collapsing into a generic failure.
 */
export function ModelSelector({
  parameter,
  value,
  onChange,
  loading,
}: {
  parameter?: ParameterDefinition;
  value: string;
  onChange: (value: string) => void;
  loading?: boolean;
}) {
  const options = (parameter?.options ?? []) as ParameterOption[];
  const selected = options.find((option) => option.value === value);
  const usable = options.filter((option) => option.enabled !== false);

  if (loading) {
    return (
      <Field label="Model" description="Looking for installed models…">
        <div className="flex h-10 items-center gap-2 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] px-3 text-sm text-[var(--color-ink-faint)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading
        </div>
      </Field>
    );
  }

  if (options.length === 0) {
    return (
      <Field
        label="Model"
        guidance={parameter?.guidance}
        error="No models found. Run scripts/download_models.sh, then check YUE2_MODEL_PATH in .env."
      >
        <div className="flex h-10 items-center rounded-[var(--radius-md)] border border-dashed border-[var(--color-line)] px-3 text-sm text-[var(--color-ink-faint)]">
          None installed
        </div>
      </Field>
    );
  }

  return (
    <Field
      label={parameter?.label ?? "Model"}
      htmlFor="model-selector"
      guidance={parameter?.guidance}
      description={
        usable.length === options.length
          ? parameter?.help
          : `${options.length - usable.length} of ${options.length} installed models cannot be loaded.`
      }
    >
      <Select value={value || "default"} onValueChange={onChange}>
        <SelectTrigger id="model-selector">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem
              key={option.value}
              value={option.value}
              disabled={option.enabled === false}
              help={
                option.enabled === false
                  ? option.disabled_reason
                  : [option.bytes ? formatBytes(option.bytes) : null, option.is_default ? "from .env" : "local"]
                      .filter(Boolean)
                      .join(" · ")
              }
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {selected ? (
        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          {selected.enabled === false ? (
            <Badge tone="danger">
              <CircleAlert className="h-3 w-3" />
              unavailable
            </Badge>
          ) : (
            <Badge tone="accent">available</Badge>
          )}
          <Badge tone="outline">
            <HardDrive className="h-3 w-3" />
            local
          </Badge>
          {selected.bytes ? <Badge tone="outline">{formatBytes(selected.bytes)}</Badge> : null}
          {selected.path ? (
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-[var(--color-ink-faint)]">
              {selected.path}
            </span>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-[var(--color-danger)]">
          The saved model &ldquo;{value}&rdquo; is not installed any more. Choose another one.
        </p>
      )}
    </Field>
  );
}
