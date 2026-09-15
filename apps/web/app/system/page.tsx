"use client";

import { Cpu, HardDrive, Server } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { useCapabilities, useSystemInfo } from "@/hooks/use-queries";
import { formatBytes } from "@/lib/format";

function Meter({ used, total, label }: { used: number; total: number; label: string }) {
  const ratio = total > 0 ? used / total : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-[var(--color-ink-muted)]">{label}</span>
        <span className="tabular-nums text-[var(--color-ink-faint)]">
          {formatBytes(used)} / {formatBytes(total)}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
        <div
          className="h-full rounded-full bg-[var(--color-accent)] transition-[width]"
          style={{ width: `${Math.min(100, ratio * 100)}%` }}
        />
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[var(--color-line)] py-1.5 last:border-b-0">
      <span className="text-xs text-[var(--color-ink-faint)]">{label}</span>
      <span className="truncate text-right font-mono text-xs">{value}</span>
    </div>
  );
}

export default function SystemPage() {
  const { data, isLoading } = useSystemInfo();
  const { data: capabilities } = useCapabilities();

  if (isLoading || !data) return <Skeleton className="h-96 w-full" />;

  const worker = data.worker.workers[0];
  const runtime = (worker?.runtime ?? {}) as Record<string, string>;
  const model = (worker?.model ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold tracking-tight">System</h1>

      {!data.worker.online ? (
        <WarningNotice>
          <p className="font-medium">The GPU worker is not running.</p>
          <p className="mt-1 text-[var(--color-ink-muted)]">
            Start it with <code className="font-mono">make worker</code>, or
            <code className="ml-1 font-mono">.venv-yue2/bin/python -m services.yue2_worker.worker</code>.
            Generations queue until it is up.
          </p>
        </WarningNotice>
      ) : null}
      {data.gpu_error ? <ErrorNotice title="GPU" message={data.gpu_error} /> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-[var(--color-accent)]" />
              GPU
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.gpus.map((gpu) => (
              <div key={gpu.index} className="space-y-2">
                <p className="text-sm font-medium">{gpu.name}</p>
                <Meter
                  used={gpu.memory_used_bytes}
                  total={gpu.memory_total_bytes}
                  label={`Device ${gpu.index} memory`}
                />
                <div className="flex flex-wrap gap-1.5">
                  <Badge>sm_{gpu.compute_capability.replace(".", "")}</Badge>
                  {gpu.utilisation_percent != null ? <Badge>{gpu.utilisation_percent}% busy</Badge> : null}
                  {gpu.temperature_c != null ? <Badge>{gpu.temperature_c}°C</Badge> : null}
                </div>
              </div>
            ))}
            <Row label="Driver" value={data.driver_version ?? "—"} />
            <Row label="CUDA (torch)" value={runtime.cuda ?? "—"} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <Server className="h-4 w-4 text-[var(--color-accent)]" />
              Worker
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Row label="State" value={worker ? worker.state : "offline"} />
            <Row label="Backend" value={String(data.app.backend)} />
            <Row label="Model loaded" value={model.loaded ? "yes" : "no"} />
            <Row label="Model" value={String(model.model ?? "—").split("/").pop() ?? "—"} />
            <Row label="Decoder" value={String(model.vae ?? "—").split("/").pop() ?? "—"} />
            <Row label="Queue depth" value={data.queue.depth} />
            <Row label="GPU job limit" value={String(data.app.max_concurrent_gpu_jobs)} />
            <Row label="Generations" value={data.queue.total_generations} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-[var(--color-accent)]" />
              Storage and runtime
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Meter used={data.disk.used_bytes} total={data.disk.total_bytes} label="Disk" />
            <div>
              <Row label="Data directory" value={data.disk.path} />
              {["torch", "transformers", "yue2-infer", "safetensors"].map((key) => (
                <Row key={key} label={key} value={runtime[key] ?? "—"} />
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Capabilities</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(capabilities?.capabilities ?? {}).map(([name, entry]) => (
              <div key={name} className="rounded-xl border border-[var(--color-line)] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm">{name.replace(/_/g, " ")}</span>
                  <Badge tone={entry.supported ? "accent" : "neutral"}>{entry.supported ? "on" : "off"}</Badge>
                </div>
                {!entry.supported && entry.reason ? (
                  <p className="mt-1 text-xs leading-relaxed text-[var(--color-ink-faint)]">{entry.reason}</p>
                ) : null}
                {entry.note ? (
                  <p className="mt-1 text-xs leading-relaxed text-[var(--color-ink-faint)]">{entry.note}</p>
                ) : null}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
