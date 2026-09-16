"use client";

import { Check, Cpu, TriangleAlert } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { useGpus, useSelectDevice } from "@/hooks/use-queries";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import type { GpuDevice } from "@/types/api";

function Meter({ device }: { device: GpuDevice }) {
  const used = device.memory_total_bytes ? device.memory_used_bytes / device.memory_total_bytes : 0;
  const tone = used > 0.85 ? "bg-[var(--color-danger)]" : used > 0.6 ? "bg-[var(--color-warn)]" : "bg-[var(--color-accent)]";
  return (
    <div className="space-y-1">
      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-3)]">
        <div className={cn("h-full rounded-full transition-[width]", tone)} style={{ width: `${used * 100}%` }} />
      </div>
      <p className="text-[11px] tabular-nums text-[var(--color-ink-faint)]">
        {formatBytes(device.memory_free_bytes)} free of {formatBytes(device.memory_total_bytes)}
      </p>
    </div>
  );
}

/**
 * Chooses which GPU the worker loads the model on.
 *
 * The list comes from the worker itself, because CUDA_VISIBLE_DEVICES can hide
 * devices from it that the API still sees — offering an index the worker
 * cannot address would not be a real choice. A change applies to the next job;
 * a run already in flight finishes where it started.
 */
export function GpuSelector() {
  const { data, isLoading } = useGpus();
  const select = useSelectDevice();

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (!data) return null;

  if (data.error || data.devices.length === 0) {
    return (
      <ErrorNotice
        title="No GPU detected"
        message={data.error ?? "The worker did not report any CUDA devices."}
        guidance="Check that the NVIDIA driver is installed and that the worker is running."
      />
    );
  }

  return (
    <div className="space-y-3">
      {data.note ? <WarningNotice>{data.note}</WarningNotice> : null}
      {data.pending_restart ? (
        <WarningNotice>
          The worker is still using GPU {data.active_index}. It moves to GPU {data.selected_index} on its next
          job; the model is reloaded then, which takes a few seconds.
        </WarningNotice>
      ) : null}

      <div
        role="radiogroup"
        aria-label="GPU used for generation"
        className="grid gap-3 md:grid-cols-2"
      >
        {data.devices.map((device) => {
          const selected = device.index === data.selected_index;
          const active = device.index === data.active_index;
          const busy = device.other_process_count > 0;
          return (
            <button
              key={device.index}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={select.isPending}
              onClick={() => select.mutate(device.index)}
              className={cn(
                "flex flex-col gap-3 rounded-[var(--radius-md)] border p-4 text-left transition-[border-color,background-color]",
                selected
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                  : "border-[var(--color-line)] hover:border-[var(--color-line-strong)] hover:bg-[var(--color-surface-2)]",
                select.isPending && "opacity-70",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <Cpu
                    className={cn(
                      "h-4 w-4 shrink-0",
                      selected ? "text-[var(--color-accent)]" : "text-[var(--color-ink-faint)]",
                    )}
                  />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      GPU {device.index} · {device.name}
                    </p>
                    <p className="text-[11px] text-[var(--color-ink-faint)]">
                      compute {device.compute_capability}
                      {device.bf16_supported === false ? " · no bf16" : ""}
                    </p>
                  </div>
                </div>
                {selected ? (
                  <Badge tone="accent">
                    <Check className="h-3 w-3" />
                    {active ? "in use" : "selected"}
                  </Badge>
                ) : null}
              </div>

              <Meter device={device} />

              <div className="flex flex-wrap items-center gap-1.5">
                {device.utilisation_percent != null ? (
                  <Badge tone="outline">{device.utilisation_percent}% busy</Badge>
                ) : null}
                {device.temperature_c != null ? <Badge tone="outline">{device.temperature_c}°C</Badge> : null}
                {busy ? (
                  <Badge tone="warn">
                    <TriangleAlert className="h-3 w-3" />
                    {device.other_process_count} other process{device.other_process_count > 1 ? "es" : ""} ·{" "}
                    {formatBytes(device.other_process_bytes)}
                  </Badge>
                ) : (
                  <Badge tone="outline">free</Badge>
                )}
                {device.bf16_supported === false ? <Badge tone="danger">bf16 unsupported</Badge> : null}
              </div>
            </button>
          );
        })}
      </div>

      {select.isError ? (
        <ErrorNotice message="The GPU could not be changed. The worker may have gone offline." />
      ) : null}
    </div>
  );
}
