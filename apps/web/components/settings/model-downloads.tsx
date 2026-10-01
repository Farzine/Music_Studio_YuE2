"use client";

import Link from "next/link";
import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ModelAssessmentCard } from "@/components/settings/model-assessment-card";
import { ModelDownloadJobs } from "@/components/settings/model-download-jobs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorNotice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { keys, useGpus } from "@/hooks/use-queries";
import { api, ApiRequestError } from "@/lib/api";
import { downloadSelectionKey } from "@/lib/download-selection";
import { formatBytes } from "@/lib/format";
import type { HubInspection, HubPreview, ModelDownloadMode } from "@/types/api";

export function ModelDownloads({ initialRepo, initialRevision, initialFile }: {
  initialRepo?: string; initialRevision?: string; initialFile?: string;
}) {
  const client = useQueryClient();
  const gpus = useGpus();
  const [repoId, setRepoId] = React.useState(initialRepo ?? "audio-cpp/Yue2-3B-GGUF");
  const [revision, setRevision] = React.useState(initialRevision ?? "");
  const [filename, setFilename] = React.useState(initialFile ?? "");
  const [evaluateGpu, setEvaluateGpu] = React.useState<number>();
  const deviceIndex = evaluateGpu ?? gpus.data?.selected_index;
  const [inspection, setInspection] = React.useState<HubInspection | null>(null);
  const [revisions, setRevisions] = React.useState<HubInspection["revisions"]>([]);
  const [mode, setMode] = React.useState<ModelDownloadMode>("single");
  const [role, setRole] = React.useState("model");
  const [selectedFiles, setSelectedFiles] = React.useState<string[]>([]);
  const selectionKey = downloadSelectionKey(repoId, revision, filename, mode, selectedFiles, deviceIndex);
  const [previewResult, setPreviewResult] = React.useState<{ key: string; preview: HubPreview }>();
  const preview = previewResult?.key === selectionKey ? previewResult.preview : undefined;
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<Error | null>(null);
  const [accepted, setAccepted] = React.useState<string>();
  const files = inspection?.candidates.filter((candidate) => candidate.model.role === role) ?? [];
  const resetSource = () => { setInspection(null); setPreviewResult(undefined); setFilename(""); setSelectedFiles([]); setError(null); setAccepted(undefined); };
  const fail = (cause: unknown) => setError(cause instanceof Error ? cause : new Error("The operation failed. Check the API connection and retry."));

  const browse = async () => {
    setBusy(true); setError(null); setInspection(null); setPreviewResult(undefined); setSelectedFiles([]);
    try {
      const result = await api.inspectModelRepo(repoId.trim(), revision.trim(), deviceIndex);
      setInspection(result); setRevisions(result.revisions);
      const models = result.candidates.filter((candidate) => candidate.model.role === role);
      if (!filename && models.length === 1) setFilename(models[0].model.filename ?? "");
    } catch (cause) { fail(cause); }
    finally { setBusy(false); }
  };
  const checkDownload = async () => {
    if (!inspection) return;
    setBusy(true); setError(null); setPreviewResult(undefined); setAccepted(undefined);
    try {
      const result = await api.previewModelDownload(repoId.trim(), filename.trim(), inspection.revision, mode, selectedFiles, deviceIndex);
      setPreviewResult({ key: selectionKey, preview: result });
    } catch (cause) { fail(cause); }
    finally { setBusy(false); }
  };
  const download = async () => {
    if (!preview?.can_download) return;
    setBusy(true); setError(null);
    try {
      const job = await api.startModelDownload(preview.repo_id, preview.filename, preview.revision, preview.mode, preview.files.map((file) => file.name));
      setAccepted(job.id); setPreviewResult(undefined);
      await client.invalidateQueries({ queryKey: keys.modelDownloads });
    } catch (cause) { fail(cause); }
    finally { setBusy(false); }
  };

  return <div className="space-y-5">
    {error ? <ErrorNotice message={error.message} guidance={error instanceof ApiRequestError ? error.guidance : undefined} /> : null}
    <Card><CardHeader><CardTitle>1 · Discover &amp; inspect</CardTitle><CardDescription>Enter a repository and branch, tag or commit. Inspection resolves an immutable commit so downloads use the exact files you reviewed.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <Field label="Resource type" htmlFor="download-resource"><select id="download-resource" value={role} disabled={busy} onChange={(event) => { setRole(event.target.value); setFilename(""); setSelectedFiles([]); setPreviewResult(undefined); }}
          className="rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-2 text-sm"><option value="model">Inference model</option><option value="vae">Native VAE</option></select></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Hugging Face repository" htmlFor="hf-repo" description="Owner/repository, for example audio-cpp/Yue2-3B-GGUF">
            <Input id="hf-repo" disabled={busy} value={repoId} onChange={(event) => { resetSource(); setRevisions([]); setRepoId(event.target.value); }} placeholder="owner/repository" /></Field>
          <Field label="Branch, tag or commit" htmlFor="hf-revision" description="Leave blank for main; revision suggestions appear after inspection.">
            <Input id="hf-revision" disabled={busy} list="hf-revisions" value={revision} onChange={(event) => { resetSource(); setRevision(event.target.value); }} placeholder="main" />
            <datalist id="hf-revisions">{revisions.map((ref) => <option key={`${ref.kind}:${ref.name}`} value={ref.name}>{ref.kind}</option>)}</datalist></Field>
          <Field label="GPU for compatibility estimate" htmlFor="download-gpu" description="Analysis only; this does not switch the worker’s GPU.">
            <select id="download-gpu" value={evaluateGpu ?? "selected"} disabled={busy} onChange={(event) => { setPreviewResult(undefined); setEvaluateGpu(event.target.value === "selected" ? undefined : Number(event.target.value)); }}
              className="w-full rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-2 text-sm">
              <option value="selected">Selected worker GPU ({gpus.data?.selected_index ?? "unknown"})</option>
              {(gpus.data?.devices ?? []).map((gpu) => <option key={gpu.index} value={gpu.index}>GPU {gpu.index} · {gpu.name ?? "Unknown"}</option>)}
            </select></Field>
        </div>
        {gpus.error ? <ErrorNotice message="GPU facts could not be refreshed. Compatibility estimates may be unavailable." guidance={gpus.error.message} /> : null}
        <div className="flex flex-wrap gap-2"><Button variant="primary" onClick={browse} disabled={busy || !repoId.trim()} loading={busy}>Inspect Repository</Button>
          <Button variant="ghost" asChild><Link href="/models/recommended">Discover recommended models</Link></Button></div>
        {inspection ? <div className="space-y-2 rounded-[var(--radius-md)] bg-[var(--color-surface-2)] p-3 text-xs text-[var(--color-ink-muted)]">
          <p className="break-all font-medium">{inspection.repo_id} · {inspection.files.length} repository files · License: {inspection.license ?? "Unknown"}</p>
          <p className="break-all">Resolved commit: {inspection.revision}</p>
          {inspection.description ? <p className="whitespace-pre-wrap break-words">{inspection.description}</p> : null}
          {inspection.warnings.map((warning) => <p key={warning} className="text-[var(--color-warn)]">{warning}</p>)}
          {!files.length ? <p>No {role === "vae" ? "VAE" : "inference model"} weight candidates found in this revision. Change the resource type to inspect other weights.</p> : null}
          <details><summary className="cursor-pointer">Branches, tags &amp; repository files</summary>
            <ul className="mt-2 max-h-64 space-y-1 overflow-auto">{inspection.revisions.map((ref) => <li key={`${ref.kind}:${ref.name}`} className="break-all">{ref.kind}: {ref.name} · {ref.commit_hash}</li>)}
              {inspection.files.map((file) => <li key={file.name} className="break-all">{file.name} · {file.extension || "No extension"} · {file.bytes == null ? "Unknown size" : formatBytes(file.bytes)}</li>)}</ul></details>
        </div> : null}
      </CardContent>
    </Card>
    <Card><CardHeader><CardTitle>2 · Select content</CardTitle><CardDescription>Select the primary model or native VAE and its related files. GGUF inference uses the bundled F16 VAE. A complete repository can include several alternate weights.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2"><Field label={role === "vae" ? "Primary VAE filename" : "Primary model filename"} htmlFor="hf-file" description="Choose a weight file below or enter its exact repository path.">
          <Input id="hf-file" disabled={busy || !inspection} value={filename} onChange={(event) => { setPreviewResult(undefined); setFilename(event.target.value); }} placeholder="yue2-3b-q4_0.gguf" /></Field>
          <Field label="Download content" htmlFor="hf-mode"><select id="hf-mode" value={mode} disabled={busy || !inspection} onChange={(event) => { setMode(event.target.value as ModelDownloadMode); setPreviewResult(undefined); }}
            className="w-full rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-2 text-sm">
            <option value="single">Model and recognized related files</option><option value="selected">Choose individual files</option><option value="repository">Complete repository</option>
          </select></Field></div>
        {!inspection ? <p className="text-sm text-[var(--color-ink-faint)]">Inspect a repository to see model files and select download content.</p> : null}
        {files.length ? <div className="max-h-64 space-y-2 overflow-auto" aria-label="Repository model files">
          {files.map((candidate) => <label key={candidate.model.id} className="flex min-w-0 items-start gap-3 rounded-[var(--radius-md)] border border-[var(--color-line)] p-3 text-sm">
            <input type="radio" name="hf-model" className="mt-1 shrink-0" checked={filename === candidate.model.filename} disabled={busy}
              onChange={() => { setPreviewResult(undefined); setFilename(candidate.model.filename ?? ""); }} />
            <span className="min-w-0 flex-1 space-y-1"><span className="block break-all font-medium">{candidate.model.filename}</span>
              <span className="block text-xs text-[var(--color-ink-faint)]">{candidate.model.format} · {candidate.model.bytes == null ? "Unknown size" : formatBytes(candidate.model.bytes)} · Parameters: {candidate.model.parameter_count ?? "Unknown"}</span>
              <span className="block text-xs text-[var(--color-ink-faint)]">Quantization: {candidate.model.quantization ?? candidate.quantization_hint ?? "Unknown"}{candidate.model.quantization == null && candidate.quantization_hint ? " (filename hint, unverified)" : ""} · {candidate.model.compatibility_status}</span>
              {candidate.model.problem ? <span className="block text-xs text-[var(--color-warn)]">{candidate.model.problem}</span> : null}
            </span></label>)}
        </div> : null}
        {mode === "selected" && inspection ? <fieldset className="max-h-64 space-y-2 overflow-auto rounded-[var(--radius-md)] border border-[var(--color-line)] p-3">
          <legend className="px-1 text-sm">Individual files · primary file always included</legend>
          {inspection.files.map((file) => <label key={file.name} className="flex items-center gap-3 text-xs"><input type="checkbox" disabled={busy || file.name === filename} checked={file.name === filename || selectedFiles.includes(file.name)}
            onChange={(event) => { setPreviewResult(undefined); setSelectedFiles((selected) => event.target.checked ? [...selected, file.name] : selected.filter((name) => name !== file.name)); }} />
            <span className="min-w-0 flex-1 break-all">{file.name}</span><span className="shrink-0">{file.bytes == null ? "Unknown size" : formatBytes(file.bytes)}</span></label>)}
        </fieldset> : null}
        <Button onClick={checkDownload} disabled={busy || !inspection || !filename.trim()}>Preview Download</Button>
      </CardContent>
    </Card>
    <Card><CardHeader><CardTitle>3 · Review &amp; download</CardTitle><CardDescription>Review exact content, available destination storage and estimated runtime compatibility. Changing the selection or evaluated GPU requires a fresh preview.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        {!preview ? <p className="text-sm text-[var(--color-ink-faint)]">Preview the current selection before downloading.</p> : <div className="space-y-4" aria-label="Download preview">
          <div className="flex flex-wrap gap-2"><Badge tone={preview.can_download ? "accent" : "danger"}>Storage: {preview.disk_status}</Badge><Badge>{preview.mode}</Badge></div>
          <p className="break-all text-sm font-medium">{preview.repo_id} · {preview.filename}</p><p className="break-all text-xs">Commit: {preview.revision}</p>
          <p className="text-sm">{preview.total_bytes == null ? `${formatBytes(preview.known_bytes)} known; total unknown` : formatBytes(preview.total_bytes)} to download · {formatBytes(preview.free_bytes)} free · {formatBytes(preview.safety_margin_bytes)} storage reserve</p>
          <p className="break-all font-mono text-xs text-[var(--color-ink-faint)]">{preview.destination}</p>
          <details open><summary className="cursor-pointer text-sm">Selected files ({preview.files.length})</summary><ul className="mt-2 max-h-64 space-y-1 overflow-auto text-xs">{preview.files.map((file) => <li key={file.name} className="break-all">{file.name} · {file.bytes == null ? "Unknown size" : formatBytes(file.bytes)}</li>)}</ul></details>
          {preview.missing_required_files.length ? <p className="break-all text-xs text-[var(--color-warn)]">Missing runtime files: {preview.missing_required_files.join(", ")}</p> : null}
          {preview.warnings.map((reason, index) => <p key={index} className="text-xs text-[var(--color-warn)]">{reason}</p>)}
          {preview.assessment ? <ModelAssessmentCard item={preview.assessment} /> : <p className="text-sm">Compatibility unknown: worker hardware facts are unavailable.</p>}
          <p className="text-xs text-[var(--color-ink-faint)]">Runtime compatibility is an estimate. Downloading does not select or load the model for a task.</p>
          <Button variant="primary" disabled={busy || !preview.can_download} onClick={download}>Start Download</Button>
        </div>}
        {accepted ? <p role="status" aria-live="polite" className="break-all text-sm text-[var(--color-accent)]">Download request accepted: {accepted}. Follow real transfer and installation progress below.</p> : null}
      </CardContent>
    </Card>
    <ModelDownloadJobs />
  </div>;
}
