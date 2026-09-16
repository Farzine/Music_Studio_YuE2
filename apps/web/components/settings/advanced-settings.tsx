"use client";

import { RotateCcw } from "lucide-react";
import * as React from "react";

import { ParameterField } from "@/components/generation/parameter-field";
import { ModelSelector } from "@/components/settings/model-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/controls";
import { changedPaths, getPath, setPath, type ConfigObject } from "@/lib/config";
import type { GenerationSchema } from "@/types/api";

/** Handled by the Create screen itself rather than the settings accordion. */
const PRIMARY = new Set([
  "prompt.style",
  "prompt.lyrics",
  "prompt.mode",
  "prompt.reference_upload_id",
  "sampling.seed",
  "sampling.control_after_generate",
  "sampling.max_duration_seconds",
]);

/**
 * Advanced settings, grouped and rendered entirely from the backend schema.
 *
 * Each section shows how many of its values differ from the defaults and can
 * be reset on its own, so exploring settings is reversible.
 */
export function AdvancedSettings({
  schema,
  config,
  defaults,
  onChange,
  loading,
}: {
  schema: GenerationSchema;
  config: ConfigObject;
  defaults: ConfigObject;
  onChange: (next: ConfigObject) => void;
  loading?: boolean;
}) {
  const groups = React.useMemo(
    () =>
      [...schema.groups]
        .sort((a, b) => a.order - b.order)
        .map((group) => ({
          ...group,
          parameters: schema.parameters.filter(
            (parameter) => parameter.group === group.key && !PRIMARY.has(parameter.key),
          ),
        }))
        .filter((group) => group.parameters.length > 0),
    [schema],
  );

  const changed = React.useMemo(() => new Set(changedPaths(defaults, config)), [defaults, config]);

  const resetGroup = (keys: string[]) => {
    let next = config;
    keys.forEach((key) => {
      next = setPath(next, key, getPath(defaults, key));
    });
    onChange(next);
  };

  return (
    <Accordion type="multiple" className="w-full">
      {groups.map((group) => {
        const keys = group.parameters.map((parameter) => parameter.key);
        const groupChanged = keys.filter((key) => changed.has(key));
        const unavailable = group.parameters.filter((parameter) => !parameter.enabled).length;

        return (
          <AccordionItem key={group.key} value={group.key}>
            <AccordionTrigger>
              <span className="flex min-w-0 flex-1 items-center gap-2">
                <span className="truncate">{group.label}</span>
                {groupChanged.length > 0 ? (
                  <Badge tone="accent">{groupChanged.length} changed</Badge>
                ) : null}
                {unavailable > 0 ? <Badge tone="warn">{unavailable} unavailable</Badge> : null}
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <p className="max-w-prose text-xs leading-relaxed text-[var(--color-ink-faint)]">
                  {group.description}
                </p>
                <Button
                  variant="ghost"
                  size="xs"
                  disabled={groupChanged.length === 0}
                  onClick={() => resetGroup(keys)}
                >
                  <RotateCcw className="h-3 w-3" />
                  Reset
                </Button>
              </div>

              <div className="grid gap-5 sm:grid-cols-2">
                {group.parameters.map((parameter) => {
                  const wide = ["text", "abc", "upload"].includes(parameter.type);
                  if (parameter.key === "model.checkpoint") {
                    return (
                      <div key={parameter.key} className="sm:col-span-2">
                        <ModelSelector
                          parameter={parameter}
                          loading={loading}
                          value={(getPath(config, parameter.key) as string) ?? "default"}
                          onChange={(next) => onChange(setPath(config, parameter.key, next))}
                        />
                      </div>
                    );
                  }
                  return (
                    <div key={parameter.key} className={wide ? "sm:col-span-2" : undefined}>
                      <ParameterField
                        parameter={parameter}
                        value={getPath(config, parameter.key)}
                        onChange={(next) => onChange(setPath(config, parameter.key, next))}
                      />
                    </div>
                  );
                })}
              </div>
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}
