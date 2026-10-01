"use client";

import { Check, Cpu, TriangleAlert } from "lucide-react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { useGpus, useSelectDevice } from "@/hooks/use-queries";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import type { GpuDevice } from "@/types/api";

function Meter({ device }: { device: GpuDevice }) {
  const used = device.memory_total_bytes && device.memory_used_bytes != null ? device.memory_used_bytes / device.memory_total_bytes : 0;
  const tone = used > 0.85 ? "bg-[var(--color-danger)]" : used > 0.6 ? "bg-[var(--color-warn)]" : "bg-[var(--color-accent)]";
  return (
    <div className="space-y-1">
      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-3)]">
        <div className={cn("h-full rounded-full transition-[width]", tone)} style={{ width: `${used * 100}%` }} />
      </div>
      <p className="text-[11px] tabular-nums text-[var(--color-ink-faint)]">
        {formatBytes(device.memory_free_bytes)} free · {formatBytes(device.memory_used_bytes)} used · {formatBytes(device.memory_total_bytes)} total
      </p>
    </div>
  );
}

/**
 * Chooses which GPU the worker loads the model on.
 *
 * The list comes from the worker itself, because CUDA_VISIBLE_DEVICES can hide
 * devices from it that the API still sees — offering an index the worker
 * cannot address would not be a real choice. Idle weights are unloaded when
 * the selection changes; a running job finishes on its original card.
 */
export function GpuSelector() {
  const { data, isLoading } = useGpus();
  const select = useSelectDevice();

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (!data) return null;
  const command = data.switch_command;
  const switching = command?.status === "queued" || command?.status === "running";

  if (data.devices.length === 0) {
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
      {data.error ? <WarningNotice>{data.error}</WarningNotice> : null}
      {data.note ? <WarningNotice>{data.note}</WarningNotice> : null}
      {command ? (
        <div role="status" aria-live="polite" className="rounded-[var(--radius-md)] border border-[var(--color-line)] p-3 text-sm">
          <p className="font-medium">{switching ? `Switching to GPU ${command.device_index}…` : command.status === "succeeded" ? `GPU ${command.device_index} selected` : "GPU switch failed"}</p>
          <p className="mt-1 text-[var(--color-ink-muted)]">{command.progress?.message ?? (switching ? "Queued: waiting for active inference to finish before switching." : "Inspect the selected GPU and runtime state below.")}</p>
          {switching && !command.worker_online ? <p className="mt-1">Worker offline. The switch has not been acknowledged; start the worker and inspect runtime state.</p> : null}
        </div>
      ) : null}
      {command?.error ? <ErrorNotice message={command.error.error_message} guidance={command.error.guidance} /> : null}

      <RadioGroup.Root
        value={String(data.selected_index)}
        onValueChange={(value) => select.mutate(Number(value))}
        disabled={select.isPending || switching}
        aria-label="GPU used for generation"
        className="grid gap-3 md:grid-cols-2"
      >
        {data.devices.map((device) => {
          const selected = device.selected;
          const active = device.index === data.active_index;
          const busy = device.other_process_count != null && device.other_process_count > 0;
          return (
            <RadioGroup.Item key={device.index} value={String(device.index)} disabled={!device.selectable} asChild>
              <button
                type="button"
                className={cn(
                  "flex flex-col gap-3 rounded-[var(--radius-md)] border p-4 text-left transition-[border-color,background-color] focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] disabled:opacity-70",
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
                        {device.selectable ? "CUDA GPU" : "Physical GPU"} {device.index} · {device.name ?? "Unknown"}
                      </p>
                      <p className="text-[11px] text-[var(--color-ink-faint)]">
                        compute {device.compute_capability ?? "unknown"}
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
                {device.error ? <span className="text-xs text-[var(--color-danger)]">{device.error}</span> : null}
                <dl className="space-y-1 break-all text-xs text-[var(--color-ink-muted)]">
                  <div><dt className="inline">CUDA: </dt><dd className="inline">{device.cuda_available == null ? "unconfirmed" : device.cuda_available ? "available" : "unavailable"} · runtime {device.cuda_runtime ?? "unknown"}</dd></div>
                  <div><dt className="inline">Driver: </dt><dd className="inline">{device.driver_version ?? "unknown"}</dd></div>
                  <div><dt className="inline">Identity: </dt><dd className="inline">{device.uuid ?? "unknown"}{device.physical_index != null ? ` · physical GPU ${device.physical_index}` : ""}</dd></div>
                  <div><dt className="inline">Loaded model: </dt><dd className="inline">{device.loaded_model ?? (data.worker_online ? "none reported" : "unknown (worker offline)")}</dd></div>
                  <div><dt className="inline">Worker allocator: </dt><dd className="inline">{formatBytes(device.allocated_bytes)} allocated · {formatBytes(device.reserved_bytes)} reserved</dd></div>
                  <div><dt className="inline">Facts: </dt><dd className="inline">{device.memory_source === "nvml" ? "live NVML memory" : "worker heartbeat memory"}; precision from {device.precision_source.replaceAll("_", " ")}. Eligibility is not an inference test.</dd></div>
                </dl>

                <div className="flex flex-wrap items-center gap-1.5">
                  {device.utilisation_percent != null ? (
                    <Badge tone="outline">{device.utilisation_percent}% busy</Badge>
                  ) : null}
                  {device.temperature_c != null ? <Badge tone="outline">{device.temperature_c}°C</Badge> : null}
                  {busy ? (
                    <Badge tone="warn">
                      <TriangleAlert className="h-3 w-3" />
                      {device.other_process_count} other process{(device.other_process_count ?? 0) > 1 ? "es" : ""} ·{" "}
                      {formatBytes(device.other_process_bytes)}
                    </Badge>
                  ) : (
                    <Badge tone="outline">{device.other_process_count == null ? "process usage unknown" : "no other compute processes"}</Badge>
                  )}
                  {(["fp16", "bf16", "fp8"] as const).map((precision) => (
                    <Badge key={precision} tone="outline">{precision.toUpperCase()} {device[`${precision}_supported`] == null ? "unknown" : device[`${precision}_supported`] ? "eligible" : "unsupported"}</Badge>
                  ))}
                </div>
              </button>
            </RadioGroup.Item>
          );
        })}
      </RadioGroup.Root>

      {select.isError ? (
        <ErrorNotice message={select.error.message} />
      ) : null}
    </div>
  );
}
