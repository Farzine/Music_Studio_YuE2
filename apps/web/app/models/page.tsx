"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive, RefreshCw } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { ModelRepair } from "@/components/settings/model-repair";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { EmptyState, ErrorNotice, Skeleton } from "@/components/ui/feedback";
import { keys, useModelCommand, useModels } from "@/hooks/use-queries";
import { api, ApiRequestError } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import type { ModelDeletionPreview, ModelEntry } from "@/types/api";

function Failure({ error }: { error: Error | null }) {
  return error ? <ErrorNotice message={error.message} guidance={error instanceof ApiRequestError ? error.guidance : undefined} /> : null;
}

function Metadata({ model }: { model: ModelEntry }) {
  const facts = {
    Repository: model.huggingface_repo ?? (model.source === "local" ? "Local installation" : "Unknown"),
    Revision: model.revision,
    File: model.filename,
    Format: model.format,
    Quantization: model.quantization,
    Precision: model.precision,
    Parameters: model.parameter_count == null ? "Unknown" : model.parameter_count.toLocaleString(),
    Size: model.bytes == null ? "Unknown" : formatBytes(model.bytes),
    Architecture: model.architecture,
    Backend: model.backend,
    "VAE requirement": model.role === "vae" ? "Not applicable (VAE)" : model.vae_requirements ?? "Unknown",
    Compatibility: model.compatibility_status,
    Installed: model.created_at == null ? "Unknown" : formatDateTime(model.created_at),
  };
  return <dl className="grid gap-x-4 gap-y-3 text-xs sm:grid-cols-2">
    {Object.entries(facts).map(([label, value]) => <div key={label} className="min-w-0">
      <dt className="text-[var(--color-ink-faint)]">{label}</dt>
      <dd className="mt-1 break-all font-medium">{value ?? "Unknown"}</dd>
    </div>)}
  </dl>;
}

export default function InstalledModelsPage() {
  const client = useQueryClient();
  const inventory = useModels();
  const [role, setRole] = React.useState("all");
  const [inspectId, setInspectId] = React.useState<string>();
  const [deleting, setDeleting] = React.useState<{ model: ModelEntry; preview: ModelDeletionPreview }>();
  const [commandId, setCommandId] = React.useState<string>();
  const command = useModelCommand(commandId);
  const inspection = useQuery({ queryKey: keys.modelInspection(inspectId ?? ""),
    queryFn: () => api.inspectModel(inspectId!), enabled: !!inspectId });
  const mutation = useMutation({ mutationFn: (action: () => Promise<void>) => action() });
  const activeCommand = !!commandId && (!command.data || ["queued", "running"].includes(command.data.status));
  const busy = mutation.isPending || activeCommand;
  const refresh = async () => {
    await Promise.all([keys.models, keys.capabilities, keys.schema, keys.health, keys.modelRecommendation, keys.taskOptions]
      .map((queryKey) => client.invalidateQueries({ queryKey })));
  };
  const requestAction = (model: ModelEntry, operation: "load" | "unload") => mutation.mutate(async () => {
    const next = await api.modelRuntimeAction(model.registry_id!, operation);
    client.setQueryData(keys.modelCommand(next.id), next);
    setCommandId(next.id);
  });
  const previewDelete = (model: ModelEntry) => mutation.mutate(async () => {
    const preview = await api.modelDeletionPreview(model.registry_id!);
    setDeleting({ model, preview });
  });
  const remove = () => {
    if (!deleting) return;
    mutation.mutate(async () => {
      const result = await api.deleteModel(deleting.model.registry_id!, deleting.preview);
      if (!result.complete) throw new Error("Deletion is incomplete. Refresh the preview before trying again.");
      setDeleting(undefined);
      await refresh();
    });
  };
  const items = inventory.data?.items.filter((model) => (model.is_local || model.registration_status === "registered") && (role === "all" || model.role === role)) ?? [];
  const inspectedModel = inspection.data?.model;

  return <div className="space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-xl font-semibold tracking-tight">Installed Models</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--color-ink-muted)]">Manage local inference models and VAEs. File readiness is separate from worker residency and GPU compatibility.</p></div>
      <div className="flex flex-wrap gap-2">
        <Button variant="surface" size="sm" onClick={() => inventory.refetch()} disabled={inventory.isFetching}><RefreshCw className="h-4 w-4" />Refresh</Button>
        <Button size="sm" asChild><Link href="/models/download">Download Model</Link></Button>
        <Button variant="ghost" size="sm" asChild><Link href="/models/recommended">Recommendations</Link></Button>
      </div>
    </header>
    <label className="flex items-center gap-3 text-sm">Show
      <select value={role} onChange={(event) => setRole(event.target.value)} className="rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-2">
        <option value="all">Models and VAEs</option><option value="model">Inference models</option><option value="vae">VAEs</option>
      </select>
    </label>
    <Failure error={inventory.error} />
    {!deleting && !inspectId ? <Failure error={mutation.error} /> : null}
    {commandId ? <Card><CardContent className="space-y-2 pt-4">
      <p role="status" aria-live="polite" className="text-sm">{command.data
        ? `${command.data.operation === "load" ? "Load" : "Unload"} request: ${command.data.status}. ${command.data.status === "succeeded" ? "Worker acknowledged; current residency is shown below." : ""}`
        : "Checking worker acknowledgement…"}</p>
      {command.data?.worker_online === false && activeCommand ? <p className="text-xs text-[var(--color-warn)]">Worker is offline. The request has not been acknowledged. Start the worker and refresh; residency is unknown.</p> : null}
      <Failure error={command.error} />
      {command.error ? <Button size="sm" variant="surface" onClick={() => command.refetch()}>Retry status check</Button> : null}
      {command.data?.error ? <ErrorNotice message={command.data.error.error_message ?? command.data.error.message ?? "Worker operation failed."} guidance={command.data.error.guidance} /> : null}
    </CardContent></Card> : null}
    <p className="text-xs text-[var(--color-ink-faint)]">Inference ready means file/runtime prerequisites passed; it does not guarantee enough VRAM. Load uses the studio default VAE and torch configuration. Task choices remain independent.</p>
    {inventory.isLoading ? <Skeleton className="h-72 w-full" /> : items.length === 0 && !inventory.error ?
      <EmptyState icon={<HardDrive className="h-6 w-6" />} title="No models in this view" description="Download a compatible model or check configured local model paths in Settings." action={<Button asChild variant="surface"><Link href="/models/download">Open downloads</Link></Button>} /> : null}
    <div className="grid gap-4 xl:grid-cols-2">
      {items.map((model) => <Card id={model.registry_id ?? undefined} key={model.registry_id ?? model.id} className="min-w-0">
        <CardHeader><div className="flex flex-wrap items-center gap-2"><CardTitle className="break-all">{model.label}</CardTitle><Badge>{model.role === "vae" ? "VAE" : "Inference model"}</Badge></div>
          <CardDescription className="break-all">{model.huggingface_repo ?? "Local installation"}</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge tone={model.download_status === "downloaded" ? "accent" : "warn"}>{model.download_status === "downloaded" ? "Downloaded" : model.download_status === "missing" ? "Files missing" : "File status unknown"}</Badge>
            <Badge tone={model.validation_status === "validated" ? "accent" : model.validation_status === "failed" ? "danger" : "neutral"}>{model.validation_status === "validated" ? "Validated" : model.validation_status === "failed" ? "Validation failed" : "Not validated"}</Badge>
            <Badge>{model.registration_status === "registered" ? "Registered" : "Discovered"}</Badge>
            <Badge tone={model.inference_ready ? "accent" : "warn"}>{model.inference_ready ? "Inference ready" : model.inference_status.replaceAll("_", " ")}</Badge>
            <Badge tone={model.currently_loaded ? "info" : "neutral"}>{model.currently_loaded === null ? "Residency unknown" : model.currently_loaded ? "Currently loaded" : "Not loaded"}</Badge>
          </div>
          <Metadata model={model} />
          <p className="break-all font-mono text-xs text-[var(--color-ink-faint)]">{model.path ?? model.id}</p>
          {model.problem ? <p className="text-xs text-[var(--color-warn)]">{model.problem}</p> : null}
          {(model.runtime ?? []).map((runtime) => <div key={runtime.worker_id} className="rounded-[var(--radius-md)] bg-[var(--color-surface-2)] p-3 text-xs">
            <p>{runtime.worker_id} · {runtime.online ? runtime.lifecycle : "Offline; last reported " + runtime.lifecycle} · {runtime.residency_mode ?? "Unknown runtime"}</p>
            <p className="mt-1 text-[var(--color-ink-muted)]">Selected GPU {runtime.device_index ?? "unknown"} · Model placement: {runtime.model_device ?? "unknown"} · VAE placement: {runtime.vae_device ?? "unknown"}</p>
            {!runtime.online ? <p>Last update: {formatDateTime(runtime.updated_at)}</p> : null}
            {runtime.error ? <p className="mt-1 text-[var(--color-danger)]">{runtime.error.error_message ?? runtime.error.message}</p> : null}
          </div>)}
          <div className="flex flex-wrap gap-2 border-t border-[var(--color-line)] pt-3">
            {model.role === "model" && model.inference_ready ? <Button size="sm" asChild><Link href={`/create?model=${encodeURIComponent(model.id)}`}>Use Model</Link></Button> : null}
            <Button size="sm" variant="surface" disabled={!model.registry_id} onClick={() => { mutation.reset(); setInspectId(model.registry_id!); }}>Inspect</Button>
            {model.role === "model" ? (["load", "unload"] as const).map((operation) => <Button key={operation} size="sm" variant="surface"
              disabled={busy || !model.runtime_actions?.[operation].allowed} title={model.runtime_actions?.[operation].reason ?? undefined}
              onClick={() => requestAction(model, operation)}>{operation === "load" ? "Load" : "Unload"}</Button>) : null}
            <Button size="sm" variant="danger" disabled={busy || !model.registry_id} onClick={() => previewDelete(model)}>{model.is_local ? "Delete" : "Remove missing installation"}</Button>
          </div>
          {model.huggingface_repo && model.registry_id ? <ModelRepair model={model} /> : null}
          {model.inference_status === "runtime_unavailable" ? <p className="text-xs">Install the GGUF runtime on the API/worker host with <code>make install-audiocpp</code>, then refresh. See <Link href="/system" className="underline">System runtime status</Link>.</p> : null}
          {model.runtime_actions?.load.reason ? <p className="text-xs text-[var(--color-ink-faint)]">{model.runtime_actions.load.reason}</p> : null}
          {model.role === "vae" ? <p className="text-xs text-[var(--color-ink-faint)]">Select this VAE independently in a task. The worker manages its resources with the inference model.</p> : null}
        </CardContent>
      </Card>)}
    </div>
    <Dialog open={!!inspectId} onOpenChange={(open) => { if (!open && !mutation.isPending) { setInspectId(undefined); mutation.reset(); } }}
      title={inspectedModel ? `Inspect ${inspectedModel.label}` : "Inspect installation"} description="File validation checks structure; runtime loading and VRAM capacity are separate checks."
      footer={<Button variant="surface" disabled={mutation.isPending || !inspectedModel} onClick={() => mutation.mutate(async () => {
        await api.validateModel(inspectId!);
        await client.invalidateQueries({ queryKey: keys.modelInspection(inspectId!) });
        await refresh();
      })}>{mutation.isPending ? "Validating…" : "Validate files"}</Button>}>
      <div className="space-y-4"><Failure error={inspection.error} /><Failure error={mutation.error} />
        {inspection.isLoading ? <Skeleton className="h-40 w-full" /> : null}
        {inspectedModel ? <><Metadata model={inspectedModel} /><p className="text-sm">Validation: {inspectedModel.validation_status.replaceAll("_", " ")}</p>
          {inspectedModel.problem ? <p className="text-xs text-[var(--color-warn)]">{inspectedModel.problem}</p> : null}
          <p className="break-all font-mono text-xs">{inspectedModel.path ?? inspectedModel.id}</p>
          <p className="text-xs">SHA256: {inspectedModel.checksum_sha256 ?? "Unknown"}<br />Commit: {inspectedModel.commit_hash ?? "Unknown"}</p>
          <details><summary className="cursor-pointer text-sm">Validation report and registry metadata</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify({ model: inspectedModel, validation: inspection.data?.validation }, null, 2)}</pre></details>
        </> : null}
      </div>
    </Dialog>
    <ConfirmDialog open={!!deleting} onOpenChange={(open) => { if (!open && !mutation.isPending) { setDeleting(undefined); mutation.reset(); } }}
      title={`Delete ${deleting?.model.label ?? "model"}?`} description={deleting?.preview.warning}
      busy={mutation.isPending} disabled={!deleting?.preview.can_delete} onConfirm={remove}
      details={deleting ? <div className="space-y-3">
        <p className="break-all font-medium">{deleting.model.huggingface_repo ?? "Local installation"} · {deleting.model.filename ?? deleting.model.label}</p>
        <p className="break-all font-mono text-xs">{deleting.preview.path}</p>
        <p>Estimated disk space reclaimed: {formatBytes(deleting.preview.estimated_reclaimed_bytes)}</p>
        {deleting.preview.blockers.map((blocker) => <p key={blocker} className="text-[var(--color-warn)]">{blocker}</p>)}
        <details><summary className="cursor-pointer">Files to remove ({deleting.preview.files.length})</summary><ul className="mt-2 max-h-40 overflow-auto text-xs">{deleting.preview.files.map((file) => <li key={file.path} className="break-all">{file.path} · {formatBytes(file.bytes)}</li>)}</ul></details>
        <Failure error={mutation.error} />
        <Button variant="surface" size="sm" disabled={mutation.isPending} onClick={() => previewDelete(deleting.model)}>Refresh deletion preview</Button>
      </div> : null} />
  </div>;
}
