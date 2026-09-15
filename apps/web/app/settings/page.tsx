"use client";

import { Trash2 } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/feedback";
import { useCapabilities, usePresets, useSystemInfo } from "@/hooks/use-queries";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/format";

export default function SettingsPage() {
  const { data: system } = useSystemInfo();
  const { data: capabilities } = useCapabilities();
  const { data: presets, refetch } = usePresets();

  if (!system || !capabilities) return <Skeleton className="h-96 w-full" />;

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle>Runtime configuration</CardTitle>
          <CardDescription>
            These come from <code className="font-mono">.env</code> and are read by both processes at startup.
            Edit that file and restart the API and the worker to change them.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          {Object.entries(system.app).map(([key, value]) => (
            <div key={key} className="rounded-xl border border-[var(--color-line)] p-3">
              <p className="text-xs uppercase tracking-wide text-[var(--color-ink-faint)]">
                {key.replace(/_/g, " ")}
              </p>
              <p className="mt-1 break-all font-mono text-sm">{String(value ?? "—")}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Models</CardTitle>
          <CardDescription>Local weight directories the worker can load.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {capabilities.models.map((model) => (
            <div
              key={model.id}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--color-line)] p-3"
            >
              <Badge tone={model.present ? "accent" : "warn"}>{model.present ? "present" : "missing"}</Badge>
              <span className="text-sm">{model.label}</span>
              <span className="font-mono text-xs text-[var(--color-ink-faint)]">{model.id}</span>
              {model.bytes ? (
                <span className="ml-auto text-xs text-[var(--color-ink-faint)]">{formatBytes(model.bytes)}</span>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Presets</CardTitle>
          <CardDescription>
            A preset is a saved configuration object. Built-in presets come from
            <code className="ml-1 font-mono">configs/presets.json</code>.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {(presets?.items ?? []).map((preset) => (
            <div
              key={preset.id}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--color-line)] p-3"
            >
              <span className="text-sm font-medium">{preset.name}</span>
              {preset.builtin ? <Badge>built-in</Badge> : null}
              <span className="text-xs text-[var(--color-ink-faint)]">{preset.description}</span>
              {!preset.builtin ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="ml-auto"
                  aria-label="Delete preset"
                  onClick={async () => {
                    await api.deletePreset(preset.id);
                    await refetch();
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
