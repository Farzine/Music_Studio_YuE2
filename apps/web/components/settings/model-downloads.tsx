"use client";

import Link from "next/link";
import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorNotice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { keys, useCapabilities, useModelDownloads } from "@/hooks/use-queries";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { HubInspection, HubPreview, HubDiscovery, ModelDownloadMode } from "@/types/api";

export function ModelDownloads() {
  const client = useQueryClient();
  const { data: downloads } = useModelDownloads();
  const { data: capabilities, error: availabilityError, isFetching: checkingAvailability } = useCapabilities();
  const [repoId, setRepoId] = React.useState("audio-cpp/Yue2-3B-GGUF");
  const [revision, setRevision] = React.useState("");
  const [filename, setFilename] = React.useState("");
  const [inspection, setInspection] = React.useState<HubInspection | null>(null);
  const [revisions, setRevisions] = React.useState<HubInspection["revisions"]>([]);
  const [mode, setMode] = React.useState<ModelDownloadMode>("single");
  const [selectedFiles, setSelectedFiles] = React.useState<string[]>([]);
  const [preview, setPreview] = React.useState<HubPreview | null>(null);
  const [discovery, setDiscovery] = React.useState<HubDiscovery | null>(null);
  const files = inspection?.candidates.filter((candidate) => candidate.model.role === "model") ?? [];
  const resetSource = () => { setInspection(null); setPreview(null); setFilename(""); setSelectedFiles([]); setError(""); };
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const completed = React.useRef("");

  const browse = async () => {
    setBusy(true);
    setError("");
    try {
      setInspection(null);
      setPreview(null);
      const result = await api.inspectModelRepo(repoId.trim(), revision.trim());
      setInspection(result);
      setRevisions(result.revisions);
      const models = result.candidates.filter((candidate) => candidate.model.role === "model");
      if (!filename && models.length === 1) setFilename(models[0].model.filename ?? "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not list repository files.");
    } finally {
      setBusy(false);
    }
  };

  const discover = async () => {
    setBusy(true);
    setError("");
    try { setDiscovery(await api.discoverModelRepos()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Discovery failed."); }
    finally { setBusy(false); }
  };

  const checkDownload = async () => {
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      setPreview(await api.previewModelDownload(repoId.trim(), filename.trim(), inspection?.revision ?? revision.trim(), mode, selectedFiles));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not preview download."); }
    finally { setBusy(false); }
  };

  const download = async () => {
    if (!preview?.can_download) return;
    setBusy(true);
    setError("");
    try {
      await api.startModelDownload(preview.repo_id, preview.filename, preview.revision, preview.mode, preview.files.map((file) => file.name));
      await client.invalidateQueries({ queryKey: keys.modelDownloads });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start download.");
    } finally {
      setBusy(false);
    }
  };

  const updateJob = async (id: string, cleanup = false) => {
    setBusy(true); setError("");
    try {
      if (cleanup) await api.cleanupModelDownload(id);
      else await api.retryModelDownload(id);
      await client.invalidateQueries({ queryKey: keys.modelDownloads });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Download action failed."); }
    finally { setBusy(false); }
  };

  React.useEffect(() => {
    const signature = (downloads?.items ?? []).filter((item) => item.status === "complete").map((item) => item.id).join(",");
    if (signature && signature !== completed.current) {
      completed.current = signature;
      client.invalidateQueries({ queryKey: keys.capabilities });
      client.invalidateQueries({ queryKey: keys.schema });
    }
  }, [downloads, client]);

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Hugging Face model ID" htmlFor="hf-repo" description="Owner/repository, for example audio-cpp/Yue2-3B-GGUF">
          <Input id="hf-repo" disabled={busy} value={repoId} onChange={(event) => { resetSource(); setRevisions([]); setRepoId(event.target.value); }} placeholder="owner/repository" />
        </Field>
        <Field label="Branch, tag or commit" htmlFor="hf-revision" description="Leave blank for main">
          <Input id="hf-revision" disabled={busy} list="hf-revisions" value={revision} onChange={(event) => { resetSource(); setRevision(event.target.value); }} placeholder="main" />
          <datalist id="hf-revisions">{revisions.map((ref) => <option key={`${ref.kind}:${ref.name}`} value={ref.name}>{ref.kind}</option>)}</datalist>
        </Field>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Model filename" htmlFor="hf-file" description="Type a filename or browse the repository">
          <Input id="hf-file" disabled={busy} value={filename} onChange={(event) => { setPreview(null); setFilename(event.target.value); }} placeholder="yue2-3b-q8_0.gguf" />
        </Field>
        <Button variant="surface" onClick={browse} disabled={busy || !repoId.trim()}>{busy ? "Working…" : "Inspect repository"}</Button>
        <Button variant="surface" onClick={checkDownload} disabled={busy || !repoId.trim() || !filename.trim()}>Preview download</Button>
        <Button variant="primary" onClick={download} disabled={busy || !preview?.can_download}>Download model</Button>
        <Button variant="ghost" onClick={discover} disabled={busy}>Discover YuE2 variants</Button>
      </div>
      <Field label="Download content" htmlFor="hf-mode" description="The primary model stays explicit. Full repository includes alternate weights, examples and documentation.">
        <select id="hf-mode" value={mode} disabled={busy} onChange={(event) => { setMode(event.target.value as ModelDownloadMode); setPreview(null); }}
          className="w-full rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-2 text-sm">
          <option value="single">Model and recognized related files</option>
          <option value="selected">Choose individual files</option>
          <option value="repository">Complete repository</option>
        </select>
      </Field>
      {mode === "selected" ? <fieldset className="max-h-64 space-y-2 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--color-line)] p-3">
        <legend className="px-1 text-sm">Related repository files</legend>
        {!inspection ? <p className="text-xs">Inspect the repository to choose related files. The primary file is always included.</p> : null}
        {inspection?.files.map((file) => <label key={file.name} className="flex items-center gap-3 text-xs">
          <input type="checkbox" disabled={busy || file.name === filename} checked={file.name === filename || selectedFiles.includes(file.name)}
            onChange={(event) => { setPreview(null); setSelectedFiles((selected) => event.target.checked ? [...selected, file.name] : selected.filter((name) => name !== file.name)); }} />
          <span className="min-w-0 flex-1 break-all">{file.name}</span>
          <span className="shrink-0">{file.bytes != null ? formatBytes(file.bytes) : "Unknown size"}</span>
        </label>)}
      </fieldset> : null}
      {files.length > 0 ? (
        <div className="max-h-64 space-y-1 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--color-line)] p-2" aria-label="Repository model files">
          {files.map((candidate) => (
            <button key={candidate.model.id} type="button" disabled={busy} aria-pressed={filename === candidate.model.filename}
              onClick={() => { setPreview(null); setFilename(candidate.model.filename ?? ""); }}
              className="flex w-full min-w-0 items-center justify-between gap-3 rounded-[var(--radius-sm)] px-3 py-2 text-left text-sm hover:bg-[var(--color-surface-2)] focus-visible:outline">
              <span className="truncate">{candidate.model.filename}</span>
              <span className="shrink-0 text-xs text-[var(--color-ink-faint)]">{candidate.model.bytes != null ? formatBytes(candidate.model.bytes) : "Unknown size"}</span>
            </button>
          ))}
        </div>
      ) : null}
      {inspection ? <div className="space-y-2 text-xs text-[var(--color-ink-muted)]" role="status">
        <p className="break-all">Resolved commit: {inspection.revision} · License: {inspection.license ?? "Unknown"}</p>
        {inspection.description ? <p>{inspection.description}</p> : null}
        {!files.length ? <p>No model weight files found in this revision.</p> : null}
        {inspection.warnings.map((warning) => <p key={warning}>{warning}</p>)}
      </div> : null}
      {preview ? <div className="space-y-3 rounded-[var(--radius-md)] border border-[var(--color-line)] p-4" aria-label="Download preview" aria-live="polite">
        <h3 className="text-sm font-medium">Download preview</h3>
        <p className="break-all text-xs">{preview.repo_id} · {preview.filename}</p>
        <p className="text-sm">{preview.total_bytes == null ? `${formatBytes(preview.known_bytes)} known; total unknown` : formatBytes(preview.total_bytes)} to download · {formatBytes(preview.free_bytes)} free at destination</p>
        <p className="break-all text-xs text-[var(--color-ink-faint)]">{preview.destination}</p>
        <ul className="list-inside list-disc text-xs">{preview.files.map((file) => <li key={file.name} className="break-all">{file.name}</li>)}</ul>
        <p className="text-xs">Format: {preview.candidate.model.format} · Parameters: {preview.candidate.model.parameter_count ?? "Unknown"} · Quantization hint: {preview.candidate.quantization_hint ?? "Unknown"} (unverified)</p>
        <p className="text-xs">GPU estimate: {preview.assessment?.status.replaceAll("_", " ") ?? "Unknown — worker hardware unavailable"}{preview.assessment?.peak_bytes != null ? ` · ${formatBytes(preview.assessment.peak_bytes)} estimated VRAM` : ""}</p>
        {[...preview.warnings, ...(preview.assessment?.reasons ?? [])].map((reason, index) => <p key={index} className="text-xs text-[var(--color-ink-muted)]">{reason}</p>)}
      </div> : null}
      {discovery ? <div className="space-y-2" aria-label="Discovered repositories">
        <p className="text-xs text-[var(--color-ink-faint)]">{discovery.note}</p>
        {!discovery.items.length ? <p className="text-sm">No quantized repositories declare this base model. You can still enter a repository ID above.</p> : null}
        {discovery.items.map((repo) => <div key={repo.repo_id} className="rounded-[var(--radius-md)] border border-[var(--color-line)] p-3">
          <Button variant="surface" size="sm" disabled={busy} onClick={() => { resetSource(); setRevisions([]); setRepoId(repo.repo_id); setRevision(""); }}>{repo.repo_id}</Button>
          {"error" in repo ? <p className="mt-2 text-xs text-[var(--color-danger)]">{repo.error.error_message}</p>
            : <p className="mt-2 text-xs">{repo.candidates.filter((c) => c.model.role === "model").length} variants · {repo.assessments.map((a) => `${a.filename}: ${a.status.replaceAll("_", " ")}`).join("; ") || "Hardware compatibility unknown"}</p>}
        </div>)}
      </div> : null}
      {error ? <ErrorNotice message={error} /> : null}
      {(downloads?.items ?? []).slice().reverse().map((item) => {
        const model = capabilities?.models.find((entry) => entry.id === item.path);
        return (
          <div key={item.id} className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-line)] p-3">
            <Badge tone={item.status === "complete" ? "accent" : item.status === "failed" ? "danger" : "warn"}>{item.status === "complete" ? "Downloaded" : item.status}</Badge>
            <span className="min-w-0 flex-1 break-all text-sm">{item.repo_id} · {item.filename}</span>
            {item.status !== "complete" && item.status !== "failed" ? <div className="w-full space-y-2" aria-live="polite">
              <p className="break-all text-xs">{item.completed_files}/{item.total_files ?? "?"} files · {item.current_file ?? item.status}</p>
              <progress className="h-2 w-full" aria-label="Overall download progress" max={100} value={item.percentage ?? undefined} />
              <p className="text-xs">{formatBytes(item.downloaded_bytes ?? 0)} / {item.total_bytes != null ? formatBytes(item.total_bytes) : "Unknown total"}
                {item.percentage != null ? ` · ${item.percentage.toFixed(1)}%` : ""}
                {item.bytes_per_second != null && item.bytes_per_second > 0 ? ` · ${formatBytes(item.bytes_per_second)}/s` : ""}
                {item.eta_seconds != null ? ` · ETA ${Math.ceil(item.eta_seconds)}s` : ""}</p>
              {item.current_file ? <div className="space-y-1">
                <progress className="h-1 w-full" aria-label={`File progress: ${item.current_file}`} max={100} value={item.current_file_percentage ?? undefined} />
                <p className="text-xs text-[var(--color-ink-faint)]">Current file: {formatBytes(item.current_file_bytes ?? 0)} / {item.current_file_total_bytes != null ? formatBytes(item.current_file_total_bytes) : "Unknown size"}</p>
              </div> : null}
            </div> : null}
            {item.status === "failed" ? <div className="flex w-full flex-wrap items-center gap-2">
              <Button size="sm" variant="surface" disabled={busy} onClick={() => updateJob(item.id)}>Retry</Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => updateJob(item.id, true)}>Remove partial files</Button>
              <span className="text-xs">Attempt {item.attempt ?? 1}{item.partial_bytes != null ? ` · ${formatBytes(item.partial_bytes)} in private staging` : ""}</span>
            </div> : null}
            {item.error ? <span className="w-full text-xs text-[var(--color-danger)]">{item.error}</span> : null}
            {item.status === "complete" && item.path ? (
              model?.inference_ready ? (
                <Button size="sm" variant="surface" asChild><Link href={`/create?model=${encodeURIComponent(item.path)}`}>Use for a song</Link></Button>
              ) : <span role="status" className="w-full text-xs text-[var(--color-ink-faint)]">
                {model?.problem ?? (availabilityError
                  ? "Download complete. Inference availability could not be checked. Refresh to retry."
                  : checkingAvailability || !capabilities
                    ? "Download complete. Checking inference availability…"
                    : "Downloaded files are not in the model inventory. Check the configured model directory.")}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
