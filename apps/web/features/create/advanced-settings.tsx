"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/controls";
import { SchemaField } from "@/features/create/schema-field";
import { getPath, setPath, type ConfigObject } from "@/lib/config";
import type { GenerationSchema } from "@/types/api";

const HIDDEN_IN_ADVANCED = new Set(["prompt.style", "prompt.lyrics", "prompt.mode"]);

/**
 * Collapsible advanced settings rendered entirely from the backend schema.
 * Nothing about a parameter is described twice in the frontend.
 */
export function AdvancedSettings({
  schema,
  config,
  onChange,
}: {
  schema: GenerationSchema;
  config: ConfigObject;
  onChange: (next: ConfigObject) => void;
}) {
  const groups = React.useMemo(
    () =>
      [...schema.groups]
        .sort((a, b) => a.order - b.order)
        .map((group) => ({
          ...group,
          parameters: schema.parameters.filter(
            (parameter) => parameter.group === group.key && !HIDDEN_IN_ADVANCED.has(parameter.key),
          ),
        }))
        .filter((group) => group.parameters.length > 0),
    [schema],
  );

  return (
    <Accordion type="multiple" className="w-full">
      {groups.map((group) => {
        const unsupported = group.parameters.filter((parameter) => !parameter.enabled).length;
        return (
          <AccordionItem key={group.key} value={group.key}>
            <AccordionTrigger>
              <span className="flex items-center gap-2">
                {group.label}
                <span className="text-xs font-normal text-[var(--color-ink-faint)]">
                  {group.parameters.length}
                </span>
                {unsupported > 0 ? <Badge tone="warn">{unsupported} unavailable</Badge> : null}
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <p className="mb-4 text-xs text-[var(--color-ink-faint)]">{group.description}</p>
              <div className="grid gap-5 sm:grid-cols-2">
                {group.parameters.map((parameter) => (
                  <div
                    key={parameter.key}
                    className={parameter.type === "text" || parameter.type === "abc" ? "sm:col-span-2" : undefined}
                  >
                    <SchemaField
                      parameter={parameter}
                      value={getPath(config, parameter.key)}
                      onChange={(value) => onChange(setPath(config, parameter.key, value))}
                    />
                  </div>
                ))}
              </div>
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}
