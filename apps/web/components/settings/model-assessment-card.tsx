import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import type { ModelAssessment, ModelRecommendation } from "@/types/api";

export function ModelAssessmentCard({ item, action, byGpu }: {
  item: ModelAssessment; action?: { href: string; label: string }; byGpu?: ModelRecommendation["by_gpu"];
}) {
  const facts = {
    "Format / backend": `${item.format} / ${item.backend ?? "Unknown"}`,
    File: item.filename ?? "Unknown",
    Architecture: item.architecture ?? "Unknown",
    "Quantization / precision": `${item.quantization ?? "Unknown"} / ${item.precision ?? "Unknown"}`,
    "Parameters (metadata)": item.parameters == null ? "Unknown" : item.parameters.toLocaleString(),
    "Model file size": item.model_bytes == null ? "Unknown" : formatBytes(item.model_bytes),
    "Estimated runtime VRAM": item.peak_bytes == null ? "Unknown" : formatBytes(item.peak_bytes),
    "Safe VRAM budget": item.safe_budget_bytes == null ? "Unknown" : formatBytes(item.safe_budget_bytes),
    "Inference prerequisites": item.inference_ready ? "Available" : "Needs validation / files or runtime",
    "VAE reference": item.vae_id ?? "Unknown",
    "CPU offload": item.offload_supported ? (item.offload_requested ? "Requested" : "Available for this backend") : "Unavailable for this backend",
  };
  return <article className="min-w-0 space-y-3 rounded-[var(--radius-md)] border border-[var(--color-line)] p-4">
    <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="min-w-0 break-all text-sm font-semibold">{item.label}</h3>
      <Badge tone={item.runnable ? "accent" : "neutral"}>{item.status === "unknown" ? "Unknown / needs validation" : item.status.replaceAll("_", " ")}</Badge></div>
    <p className="break-all text-xs text-[var(--color-ink-faint)]">{item.repo_id ?? item.id} · GPU {item.device_index}</p>
    <dl className="grid gap-2 text-xs">{Object.entries(facts).map(([label, value]) => <div key={label} className="flex flex-wrap justify-between gap-x-4 gap-y-1">
      <dt className="text-[var(--color-ink-faint)]">{label}</dt><dd className="min-w-0 break-all">{value}</dd></div>)}</dl>
    <ul className="list-disc space-y-1 pl-4 text-xs text-[var(--color-ink-muted)]">{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
    {byGpu && byGpu.length > 1 ? <details className="text-xs"><summary className="cursor-pointer">Compare GPU estimates</summary>
      <ul className="mt-2 space-y-1">{byGpu.map((gpu) => {
        const assessment = gpu.items.find((candidate) => candidate.id === item.id);
        return <li key={gpu.device_index}>GPU {gpu.device_index}: {assessment?.status.replaceAll("_", " ") ?? "Unknown"}</li>;
      })}</ul></details> : null}
    <details className="text-xs text-[var(--color-ink-faint)]"><summary className="cursor-pointer rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]">Memory estimate details</summary>
      <dl className="mt-2 space-y-1">{Object.entries({ "Expanded weights": item.estimate.weight_runtime_bytes, VAE: item.estimate.vae_bytes,
        "KV cache": item.estimate.kv_cache_bytes, "Runtime workspace": item.estimate.runtime_overhead_bytes,
        "Estimated loading RAM": item.estimate.estimated_system_ram_bytes }).map(([label, bytes]) => <div key={label} className="flex flex-wrap justify-between gap-2"><dt>{label}</dt><dd>{bytes == null ? "Unknown" : formatBytes(bytes)}</dd></div>)}</dl>
      <p className="mt-2">{item.estimate.basis.replaceAll("_", " ")} · cache: {item.estimate.kv_source.replaceAll("_", " ")} · VAE size {item.estimate.vae_size_known ? "known" : "estimated"}</p>
      <ul className="mt-2 list-disc space-y-1 pl-4">{item.estimate.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul>
    </details>
    {action ? <Button size="sm" variant="surface" asChild><Link href={action.href}>{action.label}</Link></Button> : null}
  </article>;
}
