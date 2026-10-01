"use client";

import Link from "next/link";
import { useState } from "react";

import { ModelAssessmentCard } from "@/components/settings/model-assessment-card";
import { ModelDiscovery } from "@/components/settings/model-discovery";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { Field } from "@/components/ui/field";
import { useGpus, useModelRecommendation } from "@/hooks/use-queries";
import { formatBytes } from "@/lib/format";

export default function RecommendedModelsPage() {
  const gpus = useGpus();
  const [evaluateGpu, setEvaluateGpu] = useState<number>();
  const recommendation = useModelRecommendation(evaluateGpu);
  const data = recommendation.data;
  return <div className="space-y-5">
    <header><h1 className="text-xl font-semibold tracking-tight">Recommended Models</h1>
      <p className="mt-1 max-w-2xl text-sm text-[var(--color-ink-muted)]">Review installed models and discovered repositories against a GPU’s safe memory budget. Estimates are configuration dependent and cannot guarantee a successful load.</p></header>
    <div className="flex flex-wrap items-end gap-3">
      <Field label="Evaluate GPU" htmlFor="evaluate-gpu" description="Changes this analysis only. Switch the worker’s device on System.">
        <select id="evaluate-gpu" value={evaluateGpu ?? "selected"} onChange={(event) => setEvaluateGpu(event.target.value === "selected" ? undefined : Number(event.target.value))}
          className="w-full rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-2 text-sm">
          <option value="selected">Selected worker GPU ({gpus.data?.selected_index ?? "unknown"})</option>
          {(gpus.data?.devices ?? []).map((gpu) => <option key={gpu.index} value={gpu.index}>GPU {gpu.index} · {gpu.name ?? "Unknown"}</option>)}
        </select>
      </Field>
      <Button variant="surface" size="sm" asChild><Link href="/system">Hardware &amp; model capacity</Link></Button>
      <Button variant="ghost" size="sm" disabled={recommendation.isFetching} onClick={() => recommendation.refetch()}>Refresh estimates</Button>
    </div>
    {gpus.error ? <ErrorNotice message={gpus.error.message} /> : null}
    {recommendation.error ? <ErrorNotice message={recommendation.error.message} /> : null}
    {recommendation.isLoading ? <Skeleton className="h-56 w-full" /> : null}
    {data ? <Card>
      <CardHeader><CardTitle>Installed model assessments · GPU {data.device_index}</CardTitle>
        <CardDescription>Backend ranking is deterministic: compatibility, memory requirements, then model identity. Changing the GPU does not change your task configuration.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">{data.recommended ? `Recommended selection: ${data.recommended.label}` : "No installed model is currently recommended. Review the reasons below."}</p>
        <p className="text-xs text-[var(--color-ink-faint)]">{data.note} Available VRAM: {formatBytes(data.available_bytes)}.</p>
        <p className="break-all text-xs text-[var(--color-ink-faint)]">Scenario: {data.scenario.compute_backend}, {data.scenario.memory_budget_gib} GiB native budget, VAE {data.scenario.vae}, AR offload {data.scenario.offload_ar ? "requested" : "off"}.</p>
        <div className="grid gap-3 xl:grid-cols-2">{data.items.map((item) => <ModelAssessmentCard key={item.id} item={item} byGpu={data.by_gpu}
          action={{ href: item.inference_ready && item.runnable ? `/create?model=${encodeURIComponent(item.id)}` : "/models", label: item.inference_ready && item.runnable ? "Use Model" : "Inspect installed models" }} />)}</div>
        {!data.items.length ? <EmptyState title="No model assessments available" description="Start an updated worker for GPU capability facts, then install or inspect a model." /> : null}
      </CardContent>
    </Card> : null}
    <ModelDiscovery key={evaluateGpu ?? gpus.data?.selected_index ?? "unknown"} deviceIndex={evaluateGpu ?? gpus.data?.selected_index} />
  </div>;
}
