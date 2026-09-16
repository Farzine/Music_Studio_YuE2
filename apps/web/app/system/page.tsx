"use client";

import { Cpu, HardDrive, Server } from "lucide-react";
import * as React from "react";

import { GpuSelector } from "@/components/settings/gpu-selector";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { useCapabilities, useSystemInfo } from "@/hooks/use-queries";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[var(--color-line)] py-2 last:border-b-0">
      <span className="shrink-0 text-xs text-[var(--color-ink-faint)]">{label}</span>
      <span className="min-w-0 truncate text-right font-mono text-xs">{value}</span>
    </div>
  );
}

export default function SystemPage() {
  const { data, isLoading } = useSystemInfo();
  const { data: capabilities } = useCapabilities();

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const worker = data.worker.workers[0];
  const runtime = (worker?.runtime ?? {}) as Record<string, string>;
  const model = (worker?.model ?? {}) as Record<string, unknown>;
  const disk = data.disk.used_bytes / data.disk.total_bytes;

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold tracking-tight">System</h1>

      {!data.worker.online ? (
        <WarningNotice>
          <p className="font-medium">The GPU worker is not running.</p>
          <p className="mt-1 text-[var(--color-ink-muted)]">
            Start it with <code className="font-mono">make worker</code>. Generations queue until it is up.
          </p>
        </WarningNotice>
      ) : null}
      {data.gpu_error ? <ErrorNotice title="GPU" message={data.gpu_error} /> : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-[var(--color-accent)]" />
            Graphics processor
          </CardTitle>
          <CardDescription>
            Choose which card runs the model. The change applies to the next generation; a run already in
            progress finishes on the card it started on.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <GpuSelector />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <Server className="h-4 w-4 text-[var(--color-accent)]" />
              Worker and runtime
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Row
              label="State"
              value={
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      data.worker.online ? "bg-[var(--color-accent)]" : "bg-[var(--color-ink-faint)]",
                    )}
                  />
                  {worker ? worker.state : "offline"}
                </span>
              }
            />
            <Row label="Backend" value={String(data.app.backend)} />
            <Row label="Model loaded" value={model.loaded ? "yes" : "no"} />
            <Row label="Model" value={String(model.model ?? "—").split("/").pop() ?? "—"} />
            <Row label="Decoder" value={String(model.vae ?? "—").split("/").pop() ?? "—"} />
            <Row label="Device" value={model.device_index != null ? `cuda:${model.device_index}` : "—"} />
            <Row label="Queue depth" value={data.queue.depth} />
            <Row label="GPU job limit" value={String(data.app.max_concurrent_gpu_jobs)} />
            <Row label="Driver" value={data.driver_version ?? "—"} />
            {["torch", "transformers", "yue2-infer", "cuda"].map((key) => (
              <Row key={key} label={key} value={runtime[key] ?? "—"} />
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-[var(--color-accent)]" />
              Storage
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-[var(--color-ink-muted)]">Disk</span>
                <span className="tabular-nums text-[var(--color-ink-faint)]">
                  {formatBytes(data.disk.free_bytes)} free of {formatBytes(data.disk.total_bytes)}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
                <div
                  className={cn(
                    "h-full rounded-full",
                    disk > 0.9 ? "bg-[var(--color-danger)]" : "bg-[var(--color-accent)]",
                  )}
                  style={{ width: `${Math.min(100, disk * 100)}%` }}
                />
              </div>
            </div>
            <div>
              <Row label="Data directory" value={data.disk.path} />
              <Row label="Generations" value={data.queue.total_generations} />
              {Object.entries(data.queue.by_status).map(([status, count]) => (
                <Row key={status} label={status.toLowerCase().replace(/_/g, " ")} value={String(count)} />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Capabilities</CardTitle>
          <CardDescription>
            What this installation can actually do. Anything switched off says what it needs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {Object.entries(capabilities?.capabilities ?? {}).map(([name, entry]) => (
              <div key={name} className="rounded-[var(--radius-md)] border border-[var(--color-line)] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm capitalize">{name.replace(/_/g, " ")}</span>
                  <Badge tone={entry.supported ? "accent" : "neutral"}>{entry.supported ? "on" : "off"}</Badge>
                </div>
                {!entry.supported && entry.reason ? (
                  <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-ink-faint)]">{entry.reason}</p>
                ) : null}
                {entry.note ? (
                  <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-ink-faint)]">{entry.note}</p>
                ) : null}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
