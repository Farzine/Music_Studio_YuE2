"use client";

import { Check, RotateCcw, Save } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { ConfigObject } from "@/lib/config";
import type { Preset } from "@/types/api";

export function PresetPicker({
  presets,
  activeId,
  onApply,
  onReset,
  currentConfig,
  onSaved,
}: {
  presets: Preset[];
  activeId: string | null;
  onApply: (preset: Preset) => void;
  onReset: () => void;
  currentConfig: ConfigObject;
  onSaved: () => void;
}) {
  const [saving, setSaving] = React.useState(false);
  const [name, setName] = React.useState("");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            onClick={() => onApply(preset)}
            title={preset.description}
            className={cn(
              "h-8 rounded-[var(--radius-sm)] border px-3 text-xs transition-colors",
              activeId === preset.id
                ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                : "border-[var(--color-line)] text-[var(--color-ink-muted)] hover:border-[var(--color-line-strong)] hover:text-[var(--color-ink)]",
            )}
          >
            {activeId === preset.id ? <Check className="mr-1 inline h-3 w-3" /> : null}
            {preset.name}
          </button>
        ))}
        <Button variant="ghost" size="sm" onClick={onReset} className="text-xs">
          <RotateCcw className="h-3 w-3" />
          Reset to defaults
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setSaving((value) => !value)} className="text-xs">
          <Save className="h-3 w-3" />
          Save as preset
        </Button>
      </div>

      {saving ? (
        <div className="flex gap-2">
          <Input
            placeholder="Preset name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="h-9"
          />
          <Button
            size="sm"
            variant="primary"
            disabled={!name.trim()}
            onClick={async () => {
              await api.createPreset({ name: name.trim(), config: currentConfig as Record<string, unknown> });
              setName("");
              setSaving(false);
              onSaved();
            }}
          >
            Save
          </Button>
        </div>
      ) : null}
    </div>
  );
}
