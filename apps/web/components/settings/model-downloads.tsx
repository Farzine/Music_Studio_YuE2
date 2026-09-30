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

export function ModelDownloads() {
  const client = useQueryClient();
  const { data: downloads } = useModelDownloads();
  const { data: capabilities, error: availabilityError, isFetching: checkingAvailability } = useCapabilities();
  const [repoId, setRepoId] = React.useState("audio-cpp/Yue2-3B-GGUF");
  const [revision, setRevision] = React.useState("");
  const [filename, setFilename] = React.useState("");
  const [files, setFiles] = React.useState<{ name: string; bytes: number | null }[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const completed = React.useRef("");

  const browse = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.browseModelRepo(repoId.trim(), revision.trim());
      setFiles(result.files);
      if (!filename && result.files.length === 1) setFilename(result.files[0].name);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not list repository files.");
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    setBusy(true);
    setError("");
    try {
      await api.startModelDownload(repoId.trim(), filename.trim(), revision.trim());
      await client.invalidateQueries({ queryKey: keys.modelDownloads });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start download.");
    } finally {
      setBusy(false);
    }
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
          <Input id="hf-repo" value={repoId} onChange={(event) => setRepoId(event.target.value)} placeholder="owner/repository" />
        </Field>
        <Field label="Branch, tag or commit" htmlFor="hf-revision" description="Leave blank for main">
          <Input id="hf-revision" value={revision} onChange={(event) => setRevision(event.target.value)} placeholder="main" />
        </Field>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Model filename" htmlFor="hf-file" description="Type a filename or browse the repository">
          <Input id="hf-file" value={filename} onChange={(event) => setFilename(event.target.value)} placeholder="yue2-3b-q8_0.gguf" />
        </Field>
        <Button variant="surface" onClick={browse} disabled={busy || !repoId.trim()}>Browse files</Button>
        <Button variant="primary" onClick={download} disabled={busy || !repoId.trim() || !filename.trim()}>Download model</Button>
      </div>
      {files.length > 0 ? (
        <div className="max-h-64 space-y-1 overflow-y-auto rounded-[var(--radius-md)] border border-[var(--color-line)] p-2" aria-label="Repository model files">
          {files.map((file) => (
            <button key={file.name} type="button" onClick={() => setFilename(file.name)}
              className="flex w-full min-w-0 items-center justify-between gap-3 rounded-[var(--radius-sm)] px-3 py-2 text-left text-sm hover:bg-[var(--color-surface-2)] focus-visible:outline">
              <span className="truncate">{file.name}</span>
              <span className="shrink-0 text-xs text-[var(--color-ink-faint)]">{file.bytes ? formatBytes(file.bytes) : "—"}</span>
            </button>
          ))}
        </div>
      ) : null}
      {error ? <ErrorNotice message={error} /> : null}
      {(downloads?.items ?? []).slice().reverse().map((item) => {
        const model = capabilities?.models.find((entry) => entry.id === item.path);
        return (
          <div key={item.id} className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-line)] p-3">
            <Badge tone={item.status === "complete" ? "accent" : item.status === "failed" ? "danger" : "warn"}>{item.status === "complete" ? "Downloaded" : item.status}</Badge>
            <span className="min-w-0 flex-1 break-all text-sm">{item.repo_id} · {item.filename}</span>
            {item.status === "downloading" ? <span className="text-xs">{item.completed_files}/{item.total_files ?? "?"} files · {item.current_file ?? "checking repository"}</span> : null}
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
