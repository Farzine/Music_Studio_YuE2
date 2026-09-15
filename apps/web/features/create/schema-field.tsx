"use client";

import { Info, Lock } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Slider, Switch, Tooltip } from "@/components/ui/controls";
import { FieldShell, Input, Textarea } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { ParameterDefinition } from "@/types/api";

const KIND_LABEL: Record<string, { label: string; tone: "neutral" | "info" | "warn" }> = {
  model: { label: "model", tone: "neutral" },
  workflow: { label: "ComfyUI workflow", tone: "warn" },
  post: { label: "post-processing", tone: "info" },
  app: { label: "studio", tone: "info" },
};

/**
 * Renders one parameter from the backend-served schema.
 *
 * A parameter the active backend cannot honour is shown disabled with the
 * backend's own explanation; it is never hidden and never silently ignored.
 */
export function SchemaField({
  parameter,
  value,
  onChange,
  showKind = true,
}: {
  parameter: ParameterDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
  showKind?: boolean;
}) {
  const disabled = !parameter.enabled;
  const kind = KIND_LABEL[parameter.kind];
  const id = `param-${parameter.key.replace(/\./g, "-")}`;

  const hint = (
    <span className="flex items-center gap-1.5">
      {showKind && kind && parameter.kind !== "model" ? <Badge tone={kind.tone}>{kind.label}</Badge> : null}
      {parameter.comfy.node ? (
        <Tooltip
          label={
            <span>
              ComfyUI: <code className="font-mono">{parameter.comfy.node}</code>
              {parameter.comfy.widget ? `.${parameter.comfy.widget}` : ""}
              {parameter.native.path ? (
                <>
                  <br />
                  Native: <code className="font-mono">{parameter.native.path}</code>
                </>
              ) : null}
              {parameter.comfy.note ? (
                <>
                  <br />
                  {parameter.comfy.note}
                </>
              ) : null}
            </span>
          }
        >
          <span className="cursor-help text-[var(--color-ink-faint)]">
            <Info className="h-3.5 w-3.5" />
          </span>
        </Tooltip>
      ) : null}
      {parameter.readonly ? <Lock className="h-3 w-3 text-[var(--color-ink-faint)]" /> : null}
    </span>
  );

  const shell = (children: React.ReactNode, extra?: React.ReactNode) => (
    <FieldShell
      label={parameter.label}
      help={parameter.help}
      htmlFor={id}
      hint={
        <span className="flex items-center gap-2">
          {extra}
          {hint}
        </span>
      }
      disabled={disabled}
      disabledReason={parameter.disabled_reason}
    >
      {children}
    </FieldShell>
  );

  switch (parameter.type) {
    case "bool":
      return shell(
        <div className="flex h-10 items-center">
          <Switch
            id={id}
            checked={Boolean(value)}
            disabled={disabled}
            onCheckedChange={(checked) => onChange(checked)}
          />
        </div>,
      );

    case "enum": {
      const options = parameter.options ?? [];
      const current = value == null ? "" : String(value);
      return shell(
        <Select value={current} disabled={disabled} onValueChange={(next) => onChange(next)}>
          <SelectTrigger id={id}>
            <SelectValue placeholder="Default" />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem
                key={option.value}
                value={option.value}
                help={option.enabled === false ? option.disabled_reason : option.help}
                disabled={option.enabled === false}
              >
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>,
      );
    }

    case "float":
    case "int": {
      const numeric = typeof value === "number" ? value : null;
      const min = parameter.min ?? 0;
      const max = parameter.max ?? 100;
      const step = parameter.step ?? (parameter.type === "int" ? 1 : 0.01);
      const useSlider = Number.isFinite(min) && Number.isFinite(max) && max - min <= 100000;
      return shell(
        <div className="flex items-center gap-3">
          {useSlider ? (
            <Slider
              className="flex-1"
              value={[numeric ?? (parameter.default as number) ?? min]}
              min={min}
              max={max}
              step={step}
              disabled={disabled}
              aria-label={parameter.label}
              onValueChange={([next]) => onChange(parameter.type === "int" ? Math.round(next) : next)}
            />
          ) : null}
          <Input
            id={id}
            type="number"
            className={useSlider ? "w-28" : undefined}
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
        </div>,
        parameter.unit && typeof value === "number" ? (
          <span className="tabular-nums text-[var(--color-ink-faint)]">
            {value}
            {parameter.unit}
          </span>
        ) : null,
      );
    }

    case "text":
    case "abc":
      return shell(
        <Textarea
          id={id}
          rows={parameter.rows ?? 6}
          value={typeof value === "string" ? value : ""}
          disabled={disabled}
          className={parameter.type === "abc" ? "font-mono text-xs" : undefined}
          onChange={(event) => onChange(event.target.value)}
        />,
      );

    default:
      return shell(
        <Input
          id={id}
          value={value == null ? "" : String(value)}
          disabled={disabled}
          placeholder={parameter.default == null ? "default" : String(parameter.default)}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        />,
      );
  }
}
