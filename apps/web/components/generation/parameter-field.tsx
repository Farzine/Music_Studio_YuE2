"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Slider, Switch } from "@/components/ui/controls";
import { Field, Input, Textarea } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import type { ParameterDefinition } from "@/types/api";

/**
 * Renders one parameter from the backend-served schema.
 *
 * Every control in Advanced Settings goes through here, so help, disabled
 * reasoning and the model/workflow/post distinction are defined once. A
 * parameter the active backend cannot honour is shown disabled with the
 * backend's own explanation — never hidden, and never silently ignored.
 */

const KIND: Record<string, { label: string; tone: "neutral" | "info" | "warn" }> = {
  workflow: { label: "ComfyUI only", tone: "warn" },
  post: { label: "after generation", tone: "info" },
  app: { label: "studio", tone: "info" },
};

export function ParameterField({
  parameter,
  value,
  onChange,
  className,
}: {
  parameter: ParameterDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
  className?: string;
}) {
  const disabled = !parameter.enabled;
  const id = `param-${parameter.key.replace(/\./g, "-")}`;
  const kind = KIND[parameter.kind];

  const common = {
    label: parameter.label,
    htmlFor: id,
    guidance: parameter.guidance,
    description: parameter.help,
    disabled,
    disabledReason: parameter.disabled_reason,
    className,
    actions: kind ? <Badge tone={kind.tone}>{kind.label}</Badge> : undefined,
  };

  switch (parameter.type) {
    case "bool":
      return (
        <Field {...common}>
          <div className="flex h-10 items-center">
            <Switch
              id={id}
              checked={Boolean(value)}
              disabled={disabled}
              onCheckedChange={(checked) => onChange(checked)}
            />
          </div>
        </Field>
      );

    case "enum": {
      const options = parameter.options ?? [];
      const current = value == null || value === "" ? undefined : String(value);
      return (
        <Field {...common}>
          <Select value={current} disabled={disabled} onValueChange={(next) => onChange(next)}>
            <SelectTrigger id={id}>
              <SelectValue placeholder="Default" />
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

    case "float":
    case "int": {
      const numeric = typeof value === "number" ? value : null;
      const min = parameter.min ?? 0;
      const max = parameter.max ?? 100;
      const step = parameter.step ?? (parameter.type === "int" ? 1 : 0.01);
      // A slider is only meaningful over a range a person can aim within.
      const useSlider = Number.isFinite(min) && Number.isFinite(max) && max - min <= 30000;
      const display =
        numeric == null ? "default" : `${numeric}${parameter.unit ? ` ${parameter.unit}` : ""}`;

      return (
        <Field {...common} value={display}>
          <div className="flex items-center gap-3">
            {useSlider ? (
              <Slider
                className="min-w-0 flex-1"
                value={[numeric ?? (parameter.default as number) ?? min]}
                min={min}
                max={max}
                step={step}
                disabled={disabled}
                aria-label={parameter.label}
                onValueChange={([next]) =>
                  onChange(parameter.type === "int" ? Math.round(next) : Number(next.toFixed(4)))
                }
              />
            ) : null}
            <Input
              id={id}
              type="number"
              inputMode={parameter.type === "int" ? "numeric" : "decimal"}
              className={cn(useSlider ? "w-24 shrink-0" : "w-full", "tabular-nums")}
              value={numeric ?? ""}
              min={min}
              max={max}
              step={step}
              disabled={disabled}
              placeholder={parameter.default == null ? "default" : String(parameter.default)}
              onChange={(event) => {
                const raw = event.target.value;
                if (raw === "") {
                  onChange(null);
                  return;
                }
                const parsed = parameter.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
                onChange(Number.isNaN(parsed) ? null : parsed);
              }}
            />
          </div>
        </Field>
      );
    }

    case "text":
    case "abc":
      return (
        <Field {...common}>
          <Textarea
            id={id}
            rows={parameter.rows ?? 6}
            value={typeof value === "string" ? value : ""}
            disabled={disabled}
            spellCheck={parameter.type !== "abc"}
            className={parameter.type === "abc" ? "font-mono text-xs" : undefined}
            onChange={(event) => onChange(event.target.value)}
          />
        </Field>
      );

    default:
      return (
        <Field {...common}>
          <Input
            id={id}
            value={value == null ? "" : String(value)}
            disabled={disabled}
            placeholder={parameter.default == null ? "default" : String(parameter.default)}
            onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
          />
        </Field>
      );
  }
}
