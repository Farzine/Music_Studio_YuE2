"use client";

import { ArrowLeft, Check, GitCompare, RefreshCw, Save, TriangleAlert } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/controls";
import { EmptyState, ErrorNotice, Skeleton, WarningNotice } from "@/components/ui/feedback";
import { Textarea } from "@/components/ui/field";
import { useScore } from "@/hooks/use-queries";
import { ApiRequestError, api } from "@/lib/api";

export default function ScorePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id;
  const { data, isLoading, refetch } = useScore(id);

  const [draft, setDraft] = React.useState<string | null>(null);
  const [validation, setValidation] = React.useState<{ valid: boolean; error: string | null } | null>(null);
  const [comparison, setComparison] = React.useState<Record<string, unknown> | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);

  React.useEffect(() => {
    if (data && draft === null) setDraft(data.score.edited_abc ?? data.score.source_abc);
  }, [data, draft]);

  if (isLoading) return <Skeleton className="h-96 w-full" />;
  if (!data) {
    return (
      <EmptyState
        title="No score for this generation"
        description="Direct Audio runs produce no symbolic plan. Full Song and Melody Guided runs do."
        action={
          <Button variant="surface" size="sm" onClick={() => router.back()}>
            Back
          </Button>
        }
      />
    );
  }

  const value = draft ?? "";
  const dirty = value !== (data.score.edited_abc ?? data.score.source_abc);

  const validate = async () => {
    setError(null);
    try {
      const result = await api.validateAbc(value);
      setValidation({ valid: result.valid, error: result.error });
    } catch (validationError) {
      setError(validationError instanceof Error ? validationError.message : "Validation failed");
    }
  };

  const compare = async () => {
    setError(null);
    try {
      setComparison(await api.compareScore(data.score.generation_id, value));
    } catch (compareError) {
      setError(compareError instanceof ApiRequestError ? compareError.message : "Comparison failed");
    }
  };

  const save = async () => {
    setError(null);
    setSaved(false);
    try {
      const result = await api.saveScore(data.score.generation_id, value);
      setComparison(result.comparison);
      setSaved(true);
      await refetch();
    } catch (saveError) {
      setError(saveError instanceof ApiRequestError ? saveError.message : "Save failed");
    }
  };

  const regenerate = async () => {
    setError(null);
    try {
      const job = await api.regenerateFromScore(data.score.generation_id);
      router.push(`/generations/${job.id}`);
    } catch (regenerateError) {
      setError(regenerateError instanceof ApiRequestError ? regenerateError.message : "Could not queue the run");
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <h1 className="text-xl font-semibold tracking-tight">Score</h1>
        <Badge>{data.score.origin}</Badge>
        {data.source.valid === false ? <Badge tone="danger">source invalid</Badge> : null}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Card className="min-w-0">
          <CardHeader className="pb-2">
            <CardTitle>ABC notation</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Tabs defaultValue="edit">
              <TabsList>
                <TabsTrigger value="edit">Edit</TabsTrigger>
                <TabsTrigger value="source">Source</TabsTrigger>
              </TabsList>
              <TabsContent value="edit" className="mt-3">
                <Textarea
                  rows={26}
                  value={value}
                  onChange={(event) => {
                    setDraft(event.target.value);
                    setValidation(null);
                    setSaved(false);
                  }}
                  className="font-mono text-xs leading-relaxed"
                  spellCheck={false}
                />
              </TabsContent>
              <TabsContent value="source" className="mt-3">
                <pre className="max-h-[32rem] overflow-auto rounded-xl bg-[var(--color-canvas)] p-3 font-mono text-xs leading-relaxed">
                  {data.score.source_abc}
                </pre>
              </TabsContent>
            </Tabs>

            <div className="flex flex-wrap gap-2">
              <Button variant="surface" size="sm" onClick={validate}>
                <Check className="h-3.5 w-3.5" />
                Validate
              </Button>
              <Button variant="surface" size="sm" onClick={compare}>
                <GitCompare className="h-3.5 w-3.5" />
                Compare with source
              </Button>
              <Button variant="surface" size="sm" disabled={!dirty} onClick={save}>
                <Save className="h-3.5 w-3.5" />
                Save edited score
              </Button>
              <Button variant="primary" size="sm" onClick={regenerate}>
                <RefreshCw className="h-3.5 w-3.5" />
                Regenerate from this score
              </Button>
            </div>

            {saved ? <p className="text-xs text-[var(--color-accent)]">Edited score saved.</p> : null}
            {error ? <ErrorNotice message={error} /> : null}
          </CardContent>
        </Card>

        <aside className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Validation</CardTitle>
            </CardHeader>
            <CardContent>
              {validation ? (
                validation.valid ? (
                  <p className="text-sm text-[var(--color-accent)]">
                    The score parses in the dialect YuE2 accepts.
                  </p>
                ) : (
                  <ErrorNotice message={validation.error ?? "Invalid score"} />
                )
              ) : (
                <p className="text-sm text-[var(--color-ink-faint)]">
                  Press Validate to check the score against the runtime&apos;s ABC dialect.
                </p>
              )}
              {data.source.error ? (
                <WarningNotice className="mt-3">
                  <TriangleAlert className="mr-1.5 inline h-3.5 w-3.5" />
                  The planner&apos;s own score did not parse: {data.source.error}
                </WarningNotice>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Comparison</CardTitle>
            </CardHeader>
            <CardContent>
              {comparison ? (
                <div className="space-y-2">
                  <Badge tone={comparison.match ? "accent" : "warn"}>
                    {comparison.match ? "melody, timing and tempo unchanged" : "musical content changed"}
                  </Badge>
                  <pre className="max-h-64 overflow-auto rounded-xl bg-[var(--color-canvas)] p-3 font-mono text-[11px] leading-relaxed">
                    {JSON.stringify(comparison, null, 2)}
                  </pre>
                  <p className="text-xs text-[var(--color-ink-faint)]">
                    A match deliberately allows different harmony: reharmonising is an edit, not a corruption.
                  </p>
                </div>
              ) : (
                <p className="text-sm text-[var(--color-ink-faint)]">
                  Compare to see which musical invariants survived your edit.
                </p>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
