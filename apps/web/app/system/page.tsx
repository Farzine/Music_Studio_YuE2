"use client";

import { Cpu, HardDrive, Server } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { GpuSelector } from "@/components/settings/gpu-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { useCapabilities, useModelRecommendation, useSystemInfo } from "@/hooks/use-queries";
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
  const { data: recommendation, isLoading: recommendationsLoading, error: recommendationsError } = useModelRecommendation();

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const worker = data.worker.workers.find((entry) => entry.online) ?? data.worker.workers[0];
  const runtime = (worker?.runtime ?? {}) as Record<string, string>;
  const model = (worker?.online ? worker.model : {}) as Record<string, unknown>;
  const modelError = model.error && typeof model.error === "object" ? model.error as Record<string, unknown> : null;
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
            Choose which card runs the model. Idle weights are released when you switch; a run in progress
            finishes on its original card before the next generation loads on the new one.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <GpuSelector />
        </CardContent>
      </Card>

      {recommendationsError ? <ErrorNotice title="Model estimates" message={recommendationsError.message} /> : null}
      {recommendationsLoading ? <Skeleton className="h-48 w-full" /> : null}
      <Card>
        <CardHeader>
          <CardTitle>Model capacity</CardTitle>
          <CardDescription>Heuristic limits for each worker GPU. Model metadata and runtime compatibility must be checked separately.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            {(recommendation?.capacities ?? []).map((capacity) => (
              <div key={capacity.device_index} className="rounded-[var(--radius-md)] border border-[var(--color-line)] p-4">
                <h3 className="text-sm font-semibold">GPU {capacity.device_index} · {capacity.name ?? "Unknown"}</h3>
                <Row label="Currently free VRAM" value={formatBytes(capacity.free_bytes)} />
                <Row label="Usable VRAM after reserve" value={formatBytes(capacity.usable_bytes)} />
                <Row label="Safety reserve" value={formatBytes(capacity.safety_margin_bytes)} />
                <Row label="Conservative file size" value={formatBytes(capacity.conservative_model_bytes)} />
                <Row label="Comfortable file size" value={formatBytes(capacity.comfortable_model_bytes)} />
                <Row label="Approximate upper file limit" value={formatBytes(capacity.upper_model_bytes)} />
                <p className="mt-3 text-xs text-[var(--color-ink-faint)]">Approximate parameter capacity by storage precision; quantized runtime support is assessed per model:</p>
                {capacity.quantizations.map((quant) => (
                  <Row key={quant.quantization} label={quant.quantization} value={quant.hardware_eligible === false ? "Hardware precision ineligible" : quant.approximate_parameters == null ? "Unknown" : `≈ ${(quant.approximate_parameters / 1e9).toFixed(1)}B parameters`} />
                ))}
                <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-[var(--color-ink-muted)]">{capacity.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
              </div>
            ))}
          </div>
          {!recommendationsLoading && !recommendation?.capacities.length ? <p className="text-sm text-[var(--color-ink-muted)]">No GPU capacity facts are available. Start the worker and check the NVIDIA runtime.</p> : null}
          <p className="text-xs text-[var(--color-ink-faint)]">{recommendation?.note}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recommended models</CardTitle>
          <CardDescription>Installed model assessments for GPU {recommendation?.device_index ?? "—"}. Sorted by compatibility, memory estimate and stable model ID.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {recommendation?.recommended ? <p className="rounded-[var(--radius-md)] bg-[var(--color-accent-soft)] p-3 text-sm">Recommended selection: <strong>{recommendation.recommended.label}</strong>. Estimated compatibility requires the stated configuration.</p> : <p className="text-sm text-[var(--color-ink-muted)]">No model is currently recommended. Review the reasons below; downloaded and inference-ready are separate states.</p>}
          <div className="grid gap-3 lg:grid-cols-2">
            {(recommendation?.items ?? []).map((item) => (
              <div key={item.id} className="min-w-0 rounded-[var(--radius-md)] border border-[var(--color-line)] p-4">
                <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="min-w-0 break-words text-sm font-semibold">{item.label}</h3><Badge tone={item.runnable ? "accent" : "neutral"}>{item.status === "unknown" ? "Unknown / needs validation" : item.status.replaceAll("_", " ")}</Badge></div>
                <p className="mt-2 break-all text-xs text-[var(--color-ink-faint)]">{item.repo_id ?? item.id}</p>
                <Row label="Format / backend" value={`${item.format} / ${item.backend ?? "Unknown"}`} />
                <Row label="Quantization / precision" value={`${item.quantization ?? "Unknown"} / ${item.precision ?? "Unknown"}`} />
                <Row label="Parameters (metadata)" value={item.parameters == null ? "Unknown" : item.parameters.toLocaleString()} />
                <Row label="Model file size" value={formatBytes(item.model_bytes)} />
                <Row label="Estimated runtime VRAM" value={formatBytes(item.estimate.estimated_peak_bytes)} />
                <Row label="Safe VRAM budget" value={formatBytes(item.safe_budget_bytes)} />
                <Row label="Inference prerequisites" value={item.inference_ready ? "Available" : "Needs attention"} />
                <Row label="Currently loaded" value={item.currently_loaded ? "Yes" : "Not reported"} />
                <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-[var(--color-ink-muted)]">{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                <details className="mt-3 text-xs text-[var(--color-ink-faint)]">
                  <summary className="cursor-pointer rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]">Memory estimate details</summary>
                  <Row label="Expanded weights" value={formatBytes(item.estimate.weight_runtime_bytes)} />
                  <Row label="VAE" value={formatBytes(item.estimate.vae_bytes)} />
                  <Row label="KV cache" value={formatBytes(item.estimate.kv_cache_bytes)} />
                  <Row label="Runtime workspace" value={formatBytes(item.estimate.runtime_overhead_bytes)} />
                  <Row label="Estimated loading RAM" value={formatBytes(item.estimate.estimated_system_ram_bytes)} />
                  <p className="mt-2">{item.estimate.basis.replaceAll("_", " ")} · cache: {item.estimate.kv_source.replaceAll("_", " ")}</p>
                  <ul className="mt-2 list-disc space-y-1 pl-4">{item.estimate.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
                </details>
              </div>
            ))}
          </div>
          {recommendation ? <p className="break-all text-xs text-[var(--color-ink-faint)]">Scenario: {recommendation.scenario.compute_backend}, {recommendation.scenario.memory_budget_gib} GiB native budget, VAE {recommendation.scenario.vae}, AR offload {recommendation.scenario.offload_ar ? "requested" : "off"}.</p> : null}
          <Button variant="surface" size="sm" asChild><Link href="/settings">Installed models and downloads</Link></Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>CPU and system memory</CardTitle><CardDescription>Host RAM reported by {data.memory.source.replaceAll("_", " ")}. Available memory includes reclaimable cache.</CardDescription></CardHeader>
        <CardContent>
          <Row label="CPU" value={data.memory.cpu_name ?? "Unknown"} />
          <Row label="Logical processors" value={data.memory.logical_cpu_count ?? "Unknown"} />
          <Row label="Total RAM" value={formatBytes(data.memory.total_bytes)} />
          <Row label="Available RAM" value={formatBytes(data.memory.available_bytes)} />
          <Row label="Used RAM" value={formatBytes(data.memory.used_bytes)} />
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
                  {worker?.online ? worker.state : "offline"}
                </span>
              }
            />
            <Row label="Backend" value={String(data.app.backend)} />
            <Row label="Model lifecycle" value={worker?.online ? String(model.lifecycle ?? "Not reported") : "unknown (worker offline)"} />
            <Row label="Weights retained" value={worker?.online ? model.residency_known === false ? "unknown" : model.loaded ? "yes" : "no" : "unknown (worker offline)"} />
            <Row label="Model" value={String(model.model ?? "—").split("/").pop() ?? "—"} />
            <Row label="Decoder" value={String(model.vae ?? "—").split("/").pop() ?? "—"} />
            <Row label="Device" value={model.device_index != null ? `cuda:${model.device_index}` : "—"} />
            <Row label="Model placement" value={String(model.model_device ?? "Not reported")} />
            <Row label="VAE placement" value={String(model.vae_device ?? "Not reported")} />
            {model.process_id != null && <Row label="Model process" value={String(model.process_id)} />}
            {worker?.current_command_id && <Row label="Runtime command" value={worker.current_command_id} />}
            {modelError?.error_message != null && <ErrorNotice message={String(modelError.error_message)} guidance={modelError.guidance != null ? String(modelError.guidance) : null} className="my-3" />}
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
