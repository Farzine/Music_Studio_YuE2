"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { ErrorNotice } from "@/components/ui/feedback";
import { Field } from "@/components/ui/field";
import { getPath, type ConfigObject } from "@/lib/config";
import type { TaskOptions } from "@/types/api";

export function TaskSelectors({ config, options, error, pending, onChange }: {
  config: ConfigObject; options?: TaskOptions; error: Error | null; pending: boolean;
  onChange: (path: string, value: unknown) => void;
}) {
  const selected = options?.models.find((option) => option.value === getPath(config, "model.checkpoint"));
  return <section aria-label="Task model, VAE and GPU" className="space-y-3">
    <div className="grid gap-4 md:grid-cols-3">{([
      ["Model", "model.checkpoint", options?.models], ["VAE", "model.vae", options?.vaes], ["GPU", "model.device_index", options?.gpus],
    ] as const).map(([label, path, choices]) => {
      const value = getPath(config, path);
      const displayed = label === "GPU" && value == null && options?.backend === "native" ? options.selected_device_index : value;
      const encoded = displayed == null ? "backend" : String(displayed);
      const current = choices?.find((option) => option.value === displayed);
      return <Field key={path} label={label} htmlFor={`task-${label}`} error={!pending && !current?.enabled ? current?.disabled_reason ?? `Choose an available ${label}.` : undefined}>
        <select id={`task-${label}`} value={encoded} disabled={pending || !options || !!error} onChange={(event) => onChange(path,
          label === "GPU" ? event.target.value === "backend" ? null : Number(event.target.value) : event.target.value)}
          className="w-full rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-2 text-sm">
          {!current?.enabled ? <option value={encoded} disabled>{pending ? "Checking availability…" : `Unavailable selection: ${displayed ?? "None"}`}</option> : null}
          {(choices ?? []).filter((option) => option.enabled).map((option) => <option key={String(option.value)} value={option.value == null ? "backend" : String(option.value)}>{option.label}{option.assessment ? ` · ${option.assessment.status.replaceAll("_", " ")}` : ""}</option>)}
        </select>
      </Field>;
    })}</div>
    <p className="text-xs text-[var(--color-ink-faint)]">{options?.vae_requirement ?? "Checking compatible VAE options…"}. Choices stay independent; model changes do not replace your VAE. GPU choice applies to this task.</p>
    {selected?.assessment ? <div className="space-y-1 text-xs"><Badge tone={selected.assessment.runnable ? "accent" : "neutral"}>{selected.assessment.status.replaceAll("_", " ")} (estimate)</Badge>
      {selected.assessment.reasons.map((reason) => <p key={reason} className="text-[var(--color-ink-muted)]">{reason}</p>)}</div> : null}
    {error ? <ErrorNotice message={error.message} /> : null}
    <Link href="/models" className="text-xs text-[var(--color-accent)] underline">Manage or download models and VAEs</Link>
  </section>;
}
