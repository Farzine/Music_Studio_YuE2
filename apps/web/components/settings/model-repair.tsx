"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNotice } from "@/components/ui/feedback";
import { keys } from "@/hooks/use-queries";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { ModelEntry, ModelRepairPreview } from "@/types/api";

export function ModelRepair({ model }: { model: ModelEntry }) {
  const client = useQueryClient();
  const [preview, setPreview] = useState<ModelRepairPreview>();
  const [queued, setQueued] = useState(false);
  const mutation = useMutation({ mutationFn: async (start: boolean) => {
    if (start && preview) {
      await api.repairModel(model.registry_id!, preview.confirmation_token);
      await client.invalidateQueries({ queryKey: keys.modelDownloads });
      setPreview(undefined);
      setQueued(true);
    } else setPreview(await api.modelRepairPreview(model.registry_id!));
  } });
  return <div className="space-y-2">
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="surface" disabled={mutation.isPending || !model.registry_id}
        onClick={() => { setQueued(false); mutation.mutate(false); }}>{mutation.isPending ? "Checking files…" : "Repair installation"}</Button>
      {queued ? <Link href="/models/download" className="text-xs text-[var(--color-accent)] underline">Repair queued — view progress</Link> : null}
    </div>
    {mutation.error && !preview ? <ErrorNotice message={mutation.error.message} /> : null}
    <Dialog open={!!preview} onOpenChange={(open) => { if (!open && !mutation.isPending) { setPreview(undefined); mutation.reset(); } }}
      title={`Repair ${model.label}`} description="Verified files are reused. Missing or damaged files are downloaded from the original commit and validated before installation."
      footer={<Button disabled={mutation.isPending || !preview?.can_repair} onClick={() => mutation.mutate(true)}>{mutation.isPending ? "Starting…" : "Repair and validate"}</Button>}>
      {preview ? <div className="space-y-3 text-sm">
        <p className="break-all">{preview.repo_id} · {preview.revision}</p>
        <p className="break-all font-mono text-xs">{preview.destination}</p>
        <p>Download: {preview.download_bytes == null ? "Unknown" : formatBytes(preview.download_bytes)} · Free storage: {formatBytes(preview.free_bytes)}</p>
        {preview.repair_files.length ? <ul className="max-h-60 list-disc overflow-auto pl-5">{preview.repair_files.map((file) => <li className="break-all" key={file.name}>{file.name} · {file.bytes == null ? "Unknown size" : formatBytes(file.bytes)}</li>)}</ul>
          : <p>All required files passed checks. You can refresh installation metadata and validation.</p>}
        {!preview.can_repair ? <ErrorNotice message="Insufficient storage for repair and the reserved safety margin." /> : null}
        {mutation.error ? <ErrorNotice message={mutation.error.message} /> : null}
        <Button size="sm" variant="surface" disabled={mutation.isPending} onClick={() => mutation.mutate(false)}>Refresh repair preview</Button>
      </div> : null}
    </Dialog>
  </div>;
}
