"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNotice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { keys } from "@/hooks/use-queries";
import { api, ApiRequestError } from "@/lib/api";
import { formatBytes } from "@/lib/format";

export function LocalModelBrowser() {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [folder, setFolder] = useState<string>();
  const [kind, setKind] = useState<"file" | "directory">("directory");
  const [path, setPath] = useState("");
  const [validated, setValidated] = useState("");
  const listing = useQuery({ queryKey: ["local-model-paths", folder], queryFn: () => api.browseLocalModels(folder), enabled: open });
  const validation = useMutation({ mutationFn: async () => {
    const result = await api.validateLocalModelPath(path, kind);
    setPath(result.path); setValidated(result.path); setOpen(false);
  } });
  const registration = useMutation({ mutationFn: async () => {
    const result = await api.registerLocalModel(path, kind);
    for (const queryKey of [keys.models, keys.schema, keys.capabilities, keys.modelRecommendation, keys.taskOptions]) await client.invalidateQueries({ queryKey });
    return result;
  } });
  const error = validation.error ?? registration.error;
  const busy = validation.isPending || registration.isPending;
  const choose = (next: string) => { setPath(next); setValidated(""); validation.reset(); registration.reset(); };
  return <Card>
    <CardHeader><CardTitle>Local model file or directory</CardTitle><CardDescription>Browse model storage on the API host, validate the selected path, then register an existing installation. Downloads use the configured model storage directory.</CardDescription></CardHeader>
    <CardContent className="space-y-4">
      <Field label="Selection type" htmlFor="local-path-kind"><select id="local-path-kind" disabled={busy} value={kind} onChange={(event) => { setKind(event.target.value as "file" | "directory"); choose(""); }}
        className="rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-2 text-sm"><option value="directory">Model directory</option><option value="file">Model file</option></select></Field>
      <Field label="Selected path" htmlFor="local-model-path" description="You can browse or enter an absolute path within a configured model root."><Input id="local-model-path" disabled={busy} value={path} onChange={(event) => choose(event.target.value)} placeholder="No path selected" /></Field>
      <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => { validation.reset(); setOpen(true); }}>Browse {kind === "file" ? "File" : "Folder"}</Button>
        <Button disabled={busy || !path} onClick={() => validation.mutate()}>Validate path</Button>
        <Button variant="ghost" disabled={busy || !path} onClick={() => choose("")}>Clear selection</Button>
        <Button variant="primary" disabled={busy || !validated || validated !== path} onClick={() => registration.mutate()}>Register installation</Button></div>
      {validated ? <p role="status" className="break-all text-xs text-[var(--color-accent)]">Validated existing {kind}: {validated}</p> : null}
      {registration.data ? <p role="status" className="text-sm">Registered {registration.data.model.label} ({registration.data.model.role}). <Link href="/models" className="text-[var(--color-accent)] underline">Inspect and validate model files</Link></p> : null}
      {error && !open ? <ErrorNotice message={error.message} guidance={error instanceof ApiRequestError ? error.guidance : undefined} /> : null}
      <Dialog open={open} onOpenChange={(next) => { if (!busy) setOpen(next); }} title={`Browse local model ${kind}`} description="Only configured model roots are accessible. Files are selected on the API host, including when this browser is on another machine."
        footer={<Button variant="primary" disabled={busy || !path} onClick={() => validation.mutate()}>Use selected path</Button>}>
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">{listing.data?.roots.map((root) => <Button key={root} size="sm" disabled={busy} onClick={() => setFolder(root)} className="max-w-full"><span className="truncate">{root}</span></Button>)}</div>
          {listing.data && !listing.data.roots.length ? <p className="text-sm">No existing model roots. Download a model or configure MODEL_BROWSER_ROOTS as a JSON array of trusted directories in .env.</p> : null}
          <p className="break-all font-mono text-xs">{listing.data?.path ?? "Choose a model root above"}</p>
          {listing.data?.parent ? <Button size="sm" disabled={busy} onClick={() => setFolder(listing.data!.parent!)}>Parent directory</Button> : null}
          {kind === "directory" && listing.data?.path ? <Button size="sm" disabled={busy} onClick={() => choose(listing.data!.path!)}>Select this directory</Button> : null}
          <div className="max-h-64 space-y-2 overflow-auto">{listing.data?.items.map((item) => <div key={item.path} className="flex min-w-0 flex-wrap items-center gap-2 border-b border-[var(--color-line)] py-2 text-xs">
            <span className="min-w-0 flex-1 break-all">{item.name} · {item.kind}{item.bytes == null ? "" : ` · ${formatBytes(item.bytes)}`}</span>
            {item.kind === "directory" ? <Button size="sm" disabled={busy} onClick={() => setFolder(item.path)}>Open</Button> : null}
            {item.kind === kind ? <Button size="sm" disabled={busy} onClick={() => choose(item.path)}>Select</Button> : null}
          </div>)}</div>
          <p className="break-all text-xs">Selected: {path || "None"}</p>
          {listing.isFetching ? <p role="status" className="text-xs">Reading model directory…</p> : null}
          {listing.data?.truncated ? <p className="text-xs">Showing up to 1000 entries. Enter an exact path to select another item.</p> : null}
          {listing.error ? <ErrorNotice message={listing.error.message} /> : null}
          {validation.error ? <ErrorNotice message={validation.error.message} /> : null}
        </div>
      </Dialog>
    </CardContent>
  </Card>;
}
