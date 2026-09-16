"use client";

import { ChevronDown } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/feedback";
import { useManifest } from "@/hooks/use-queries";
import { formatBytes, formatDuration } from "@/lib/format";
import type { GenerationJob } from "@/types/api";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[var(--color-line)] py-1.5 last:border-b-0">
      <span className="shrink-0 text-xs text-[var(--color-ink-faint)]">{label}</span>
      <span className="min-w-0 truncate text-right font-mono text-xs text-[var(--color-ink)]">{value}</span>
    </div>
  );
}

/** Everything needed to explain and reproduce a result, kept out of the way. */
export function TechnicalDetails({ job }: { job: GenerationJob }) {
  const [open, setOpen] = React.useState(false);
  const { data: manifest, isLoading } = useManifest(job.status === "COMPLETED" ? job.id : undefined);

  const weights = (manifest?.weights ?? {}) as Record<
    string,
    { config_sha256?: string; files?: Record<string, { sha256: string; bytes: number }> }
  >;
  const runtime = (manifest?.runtime ?? {}) as Record<string, unknown>;
  const hardware = (manifest?.hardware ?? {}) as Record<string, unknown>;
  const timing = job.timing;

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-surface)]">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex min-h-12 w-full items-center justify-between gap-2 px-5 py-3.5 text-sm font-medium"
      >
        Technical details
        <ChevronDown className={open ? "h-4 w-4 rotate-180 transition-transform" : "h-4 w-4 transition-transform"} />
      </button>
      {open ? (
        <div className="grid gap-6 border-t border-[var(--color-line)] p-5 xl:grid-cols-2">
          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
              Identity
            </h4>
            <Row label="Generation" value={job.id} />
            <Row label="Project" value={job.project_id} />
            <Row label="Request identity" value={job.request_identity?.slice(0, 16) ?? "—"} />
            <Row label="Worker" value={job.worker_id ?? "—"} />
            <Row label="Seed" value={job.config.sampling.seed} />
            <Row label="Mode" value={`${job.config.prompt.mode} (cot)`} />
          </section>

          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
              Timing
            </h4>
            <Row label="Queue wait" value={formatDuration(timing.queue_wait_seconds)} />
            <Row label="Model load" value={formatDuration(timing.model_load_seconds)} />
            <Row label="Planning" value={formatDuration(timing.planning_seconds)} />
            <Row label="Acoustic tokens" value={formatDuration(timing.semantic_seconds)} />
            <Row label="Synthesis" value={formatDuration(timing.synthesis_seconds)} />
            <Row label="Decoding" value={formatDuration(timing.decode_seconds)} />
            <Row label="Total" value={formatDuration(timing.total_seconds)} />
            <Row label="Audio produced" value={formatDuration(timing.output_seconds)} />
            <Row label="GPU peak" value={timing.gpu_peak_bytes ? formatBytes(timing.gpu_peak_bytes) : "—"} />
          </section>

          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
              Weights and runtime
            </h4>
            {isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : manifest ? (
              <>
                {Object.entries(weights).map(([role, value]) => (
                  <React.Fragment key={role}>
                    <Row label={`${role} config`} value={value?.config_sha256?.slice(0, 16) ?? "—"} />
                    {Object.entries(value?.files ?? {}).map(([name, file]) => (
                      <Row
                        key={name}
                        label={`${role} ${name}`}
                        value={`${file.sha256.slice(0, 12)} · ${formatBytes(file.bytes)}`}
                      />
                    ))}
                  </React.Fragment>
                ))}
                {["torch", "transformers", "yue2-infer", "cuda"].map((key) => (
                  <Row key={key} label={key} value={(runtime[key] as string) ?? "—"} />
                ))}
                <Row label="Runtime hash" value={String(runtime.runtime_sha256 ?? "—").slice(0, 16)} />
              </>
            ) : (
              <p className="text-xs text-[var(--color-ink-faint)]">
                The manifest is written when a generation completes.
              </p>
            )}
          </section>

          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
              Hardware and artifacts
            </h4>
            <Row label="GPU" value={(hardware.name as string) ?? "—"} />
            <Row
              label="VRAM"
              value={hardware.total_bytes ? formatBytes(hardware.total_bytes as number) : "—"}
            />
            {job.artifacts.map((artifact) => (
              <Row
                key={artifact.path}
                label={artifact.kind}
                value={`${artifact.path.split("/").pop()} · ${formatBytes(artifact.bytes)}`}
              />
            ))}
          </section>

          <section className="xl:col-span-2">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">
              Effective configuration
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(flatten(job.config as unknown as Record<string, unknown>)).map(([key, value]) => (
                <Badge key={key}>
                  <span className="text-[var(--color-ink-faint)]">{key}</span>
                  <span className="font-mono">{String(value)}</span>
                </Badge>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function flatten(source: Record<string, unknown>, prefix = ""): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  Object.entries(source).forEach(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      Object.assign(result, flatten(value as Record<string, unknown>, path));
    } else if (value !== null && value !== "" && key !== "lyrics" && key !== "style" && key !== "abc") {
      result[path] = value;
    }
  });
  return result;
}
