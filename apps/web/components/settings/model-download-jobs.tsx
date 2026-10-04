"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { keys, useModelDownloads, useModels } from "@/hooks/use-queries";
import { api, ApiRequestError } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { ModelDownload } from "@/types/api";

export function ModelDownloadJobs() {
  const client = useQueryClient();
  const downloads = useModelDownloads();
  const models = useModels();
  const completed = useRef("");
  const [cleanup, setCleanup] = useState<ModelDownload>();
  const mutation = useMutation({ mutationFn: async ({ id, remove }: { id: string; remove: boolean }) => {
    if (remove) await api.cleanupModelDownload(id);
    else await api.retryModelDownload(id);
    setCleanup(undefined);
    await client.invalidateQueries({ queryKey: keys.modelDownloads });
  } });
  useEffect(() => {
    const signature = (downloads.data?.items ?? []).filter((item) => item.status === "complete").map((item) => item.id).join(",");
    if (signature && signature !== completed.current) {
      completed.current = signature;
      for (const queryKey of [keys.models, keys.capabilities, keys.schema, keys.health, keys.modelRecommendation, keys.taskOptions]) client.invalidateQueries({ queryKey });
    }
  }, [client, downloads.data]);
  const error = mutation.error;
  return <Card>
    <CardHeader><CardTitle>Downloads &amp; installation</CardTitle><CardDescription>Queued → Downloading → Verifying → Registering → Completed. Progress comes from transferred and verified bytes; installation readiness is reported separately.</CardDescription></CardHeader>
    <CardContent className="space-y-4">
      <Button size="sm" variant="ghost" disabled={downloads.isFetching || models.isFetching} onClick={() => { downloads.refetch(); models.refetch(); }}>Refresh download &amp; inventory status</Button>
      {downloads.error ? <ErrorNotice message={downloads.error.message} /> : null}
      {models.error ? <ErrorNotice message="Downloads are recorded, but current installation readiness could not be refreshed." guidance={models.error.message} /> : null}
      {error && !cleanup ? <ErrorNotice message={error.message} guidance={error instanceof ApiRequestError ? error.guidance : undefined} /> : null}
      {downloads.isLoading ? <Skeleton className="h-36 w-full" /> : !downloads.error && !downloads.data?.items.length ? <EmptyState title="No downloads yet" description="Inspect a repository and review its selected content above to start a download." /> : null}
      {(downloads.data?.items ?? []).slice().reverse().map((item) => {
        const model = models.data?.items.find((entry) => (entry.registry_id && entry.registry_id === item.registry_id) || entry.id === item.path);
        return <article key={item.id} className="min-w-0 space-y-3 rounded-[var(--radius-md)] border border-[var(--color-line)] p-4">
          <div className="flex flex-wrap items-start gap-2"><h3 className="min-w-0 flex-1 break-all text-sm font-semibold">{item.repo_id} · {item.filename}</h3>
            <Badge tone={item.status === "complete" ? "accent" : item.status === "failed" ? "danger" : "warn"}>{item.status === "complete" ? "Download completed" : item.status}</Badge></div>
          <p className="break-all text-xs text-[var(--color-ink-faint)]">Revision: {item.revision} · {item.mode ?? "Legacy single package"} · Attempt {item.attempt ?? 1}</p>
          {item.status !== "complete" ? <div className="space-y-2">
            <p role="status" aria-live="polite" className="break-all text-xs">{item.completed_files}/{item.total_files ?? "?"} files · {item.current_file ?? item.status}</p>
            <progress className="h-2 w-full" aria-label={`Overall download progress for ${item.filename}`} max={100} value={item.percentage ?? undefined} />
            <p className="text-xs">{item.downloaded_bytes == null ? "Unknown transferred bytes" : formatBytes(item.downloaded_bytes)} / {item.total_bytes == null ? "Unknown total" : formatBytes(item.total_bytes)}
              {item.percentage != null ? ` · ${item.percentage.toFixed(1)}%` : ""}
              {item.bytes_per_second != null && item.bytes_per_second > 0 ? ` · ${formatBytes(item.bytes_per_second)}/s` : ""}
              {item.eta_seconds != null ? ` · ETA ${Math.ceil(item.eta_seconds)}s` : " · ETA unknown"}</p>
            {item.current_file ? <div className="space-y-1"><progress className="h-1 w-full" aria-label={`File progress: ${item.current_file}`} max={100} value={item.current_file_percentage ?? undefined} />
              <p className="text-xs text-[var(--color-ink-faint)]">Current file: {item.current_file_bytes == null ? "Unknown" : formatBytes(item.current_file_bytes)} / {item.current_file_total_bytes == null ? "Unknown size" : formatBytes(item.current_file_total_bytes)}</p></div> : null}
          </div> : null}
          {item.error ? <ErrorNotice message={item.error} /> : null}
          {item.status === "failed" ? <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={mutation.isPending} onClick={() => { mutation.reset(); mutation.mutate({ id: item.id, remove: false }); }}>Retry download</Button>
            <Button size="sm" variant="danger" disabled={mutation.isPending} onClick={() => { mutation.reset(); setCleanup(item); }}>Remove partial files</Button>
            <span className="text-xs text-[var(--color-ink-faint)]">{item.partial_bytes == null ? "Staging size unknown" : `${formatBytes(item.partial_bytes)} in private staging`}</span>
          </div> : null}
          {item.status === "complete" ? <div className="space-y-2">
            <p className="text-xs">Downloaded bytes: {item.downloaded_bytes == null ? "Unknown (legacy request)" : formatBytes(item.downloaded_bytes)} · Total: {item.total_bytes == null ? "Unknown" : formatBytes(item.total_bytes)}</p>
            <div className="flex flex-wrap gap-2"><Badge>Validation: {model?.validation_status ?? item.validation_status ?? "Unknown"}</Badge>
              <Badge>Registration: {model?.registration_status ?? "Unknown"}</Badge>
              <Badge tone={model?.inference_ready && !models.error ? "accent" : "neutral"}>Inference: {models.error ? "Unknown" : model?.inference_status.replaceAll("_", " ") ?? "Needs current inventory check"}</Badge></div>
            {model?.problem && !models.error ? <p className="text-xs text-[var(--color-warn)]">{model.problem}</p> : null}
            <div className="flex flex-wrap gap-2">{model?.role === "model" && model.inference_ready && !models.error ? <Button size="sm" variant="primary" asChild><Link href={`/create?model=${encodeURIComponent(model.id)}`}>Use Model</Link></Button> : null}
              <Button size="sm" asChild><Link href={model?.registry_id ? `/models#${model.registry_id}` : "/models"}>Repair or delete installation</Link></Button></div>
            {item.path ? <p className="break-all font-mono text-xs text-[var(--color-ink-faint)]">{item.path}</p> : null}
          </div> : null}
        </article>;
      })}
    </CardContent>
    <ConfirmDialog open={!!cleanup} onOpenChange={(open) => { if (!open && !mutation.isPending) { setCleanup(undefined); mutation.reset(); } }}
      title="Remove incomplete download files?" description="This deletes the failed request’s private staging files. Retry will need to transfer those files again."
      busy={mutation.isPending} confirmLabel="Remove partial files" onConfirm={() => { if (cleanup) mutation.mutate({ id: cleanup.id, remove: true }); }}
      details={<div className="space-y-2"><p className="break-all">{cleanup?.repo_id} · {cleanup?.filename}</p><p className="break-all text-xs">Request: {cleanup?.id}</p>
        <p>Estimated space: {cleanup?.partial_bytes == null ? "Unknown" : formatBytes(cleanup.partial_bytes)}</p>
        {error ? <ErrorNotice message={error.message} guidance={error instanceof ApiRequestError ? error.guidance : undefined} /> : null}</div>} />
  </Card>;
}
