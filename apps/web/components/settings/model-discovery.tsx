"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect } from "react";

import { ModelAssessmentCard } from "@/components/settings/model-assessment-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorNotice } from "@/components/ui/feedback";
import { api, ApiRequestError } from "@/lib/api";

export function ModelDiscovery({ deviceIndex }: { deviceIndex?: number }) {
  const discovery = useMutation({ mutationFn: () => api.discoverModelRepos(deviceIndex) });
  const reset = discovery.reset;
  useEffect(() => { reset(); }, [deviceIndex, reset]);
  return <Card>
    <CardHeader><CardTitle>Discover quantized YuE2 models</CardTitle>
      <CardDescription>Inspect repositories that declare YuE2-3B as their base model. Discovery reads metadata; choose a file and review a download preview to install it.</CardDescription></CardHeader>
    <CardContent className="space-y-4">
      <Button variant="surface" loading={discovery.isPending} onClick={() => discovery.mutate()}>Discover YuE2 variants</Button>
      {discovery.error ? <ErrorNotice message={discovery.error.message} guidance={discovery.error instanceof ApiRequestError ? discovery.error.guidance : undefined} /> : null}
      {discovery.data ? <>
        <p className="text-xs text-[var(--color-ink-faint)]">{discovery.data.note}</p>
        {!discovery.data.items.length ? <EmptyState title="No declared quantized repositories found" description="Enter a repository ID on Download Model to inspect it directly." /> : null}
        {discovery.data.items.map((repo) => <section key={repo.repo_id} className="space-y-3 border-t border-[var(--color-line)] pt-4">
          <h3 className="break-all text-sm font-semibold">{repo.repo_id}</h3>
          {"error" in repo ? <ErrorNotice message={repo.error.error_message} /> : <>
            {repo.description ? <p className="text-sm text-[var(--color-ink-muted)]">{repo.description}</p> : null}
            <p className="break-all text-xs text-[var(--color-ink-faint)]">Commit: {repo.revision} · License: {repo.license ?? "Unknown"} · Assessed GPU {repo.device_index}</p>
            {repo.warnings.map((warning) => <p key={warning} className="text-xs text-[var(--color-warn)]">{warning}</p>)}
            <div className="grid gap-3 xl:grid-cols-2">{repo.assessments.map((item) => <ModelAssessmentCard key={item.id} item={item} byGpu={repo.by_gpu}
              action={{ label: "Inspect & preview download", href: `/models/download?${new URLSearchParams({ repo: repo.repo_id, revision: repo.revision, ...(item.filename ? { file: item.filename } : {}) })}` }} />)}</div>
            {!repo.assessments.length ? <p className="text-sm text-[var(--color-ink-muted)]">No inference-model candidates found in this revision.</p> : null}
          </>}
        </section>)}
      </> : null}
    </CardContent>
  </Card>;
}
