"use client";

import { CircleAlert, CircleCheck, Info, TriangleAlert, Wand2 } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatBytes, formatDuration } from "@/lib/format";
import type { BudgetEstimate, ModelLimits } from "@/types/api";

/**
 * Pre-generation token budget.
 *
 * The model writes a song of whatever length its style, lyrics and score imply,
 * and the duration limit is a hard stop rather than a target. This shows how
 * much of the model's context the request leaves for audio, before anything is
 * queued, so a request that cannot fit is caught here rather than several
 * minutes into a run.
 */

const TONE = {
  SAFE: {
    badge: "accent" as const,
    icon: CircleCheck,
    border: "border-[var(--color-line)]",
    label: "Fits comfortably",
  },
  WARNING: {
    badge: "warn" as const,
    icon: TriangleAlert,
    border: "border-[color-mix(in_oklch,var(--color-warn)_35%,transparent)]",
    label: "Close to the limit",
  },
  UNSAFE: {
    badge: "danger" as const,
    icon: CircleAlert,
    border: "border-[color-mix(in_oklch,var(--color-danger)_40%,transparent)]",
    label: "Will not fit",
  },
};

function Figure({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] uppercase tracking-wide text-[var(--color-ink-faint)]">{label}</p>
      <p className="mt-0.5 truncate font-mono text-sm tabular-nums">{value}</p>
      {hint ? <p className="mt-0.5 truncate text-[11px] text-[var(--color-ink-faint)]">{hint}</p> : null}
    </div>
  );
}

export function BudgetPanel({
  estimate,
  limits,
  onAdjust,
  className,
}: {
  estimate: BudgetEstimate;
  limits?: ModelLimits;
  onAdjust?: (seconds: number) => void;
  className?: string;
}) {
  const tone = TONE[estimate.risk];
  const Icon = tone.icon;
  const used = estimate.available_generation_tokens
    ? estimate.requested_tokens / estimate.available_generation_tokens
    : 0;

  return (
    <section
      aria-live="polite"
      className={cn(
        "rounded-[var(--radius-md)] border bg-[var(--color-canvas)] p-4",
        tone.border,
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Icon
            className={cn(
              "h-4 w-4",
              estimate.risk === "SAFE"
                ? "text-[var(--color-accent)]"
                : estimate.risk === "WARNING"
                  ? "text-[var(--color-warn)]"
                  : "text-[var(--color-danger)]",
            )}
          />
          <h3 className="text-sm font-medium">Audio token budget</h3>
        </div>
        <Badge tone={tone.badge}>{tone.label}</Badge>
      </div>

      <div className="mt-3 space-y-1.5">
        <div className="h-2 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-[var(--duration-base)]",
              estimate.risk === "UNSAFE"
                ? "bg-[var(--color-danger)]"
                : estimate.risk === "WARNING"
                  ? "bg-[var(--color-warn)]"
                  : "bg-[var(--color-accent)]",
            )}
            style={{ width: `${Math.min(100, used * 100)}%` }}
          />
        </div>
        <p className="text-[11px] tabular-nums text-[var(--color-ink-faint)]">
          {estimate.requested_tokens.toLocaleString()} of {estimate.available_generation_tokens.toLocaleString()}{" "}
          audio tokens ({Math.round(used * 100)}%)
        </p>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure
          label="Requested"
          value={formatDuration(estimate.requested_seconds)}
          hint={`${estimate.requested_tokens.toLocaleString()} tokens`}
        />
        <Figure
          label="Safe capacity"
          value={formatDuration(estimate.max_safe_seconds)}
          hint={`${estimate.max_safe_tokens.toLocaleString()} tokens`}
        />
        <Figure
          label="Style and lyrics"
          value={`${estimate.prefix_breakdown.instruction_style_lyrics.toLocaleString()}`}
          hint="tokens of context"
        />
        <Figure
          label="Key/value cache"
          value={formatBytes(estimate.kv_cache_bytes)}
          hint={estimate.cfg_branches > 1 ? `${estimate.cfg_branches} guidance branches` : "reserved on the GPU"}
        />
      </div>

      {estimate.reasons.length > 0 ? (
        <ul className="mt-3 space-y-1 border-t border-[var(--color-line)] pt-3">
          {estimate.reasons.map((reason) => (
            <li key={reason} className="flex gap-2 text-xs leading-relaxed text-[var(--color-ink-muted)]">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-ink-faint)]" />
              {reason}
            </li>
          ))}
        </ul>
      ) : null}

      {estimate.risk !== "SAFE" ? (
        <div className="mt-3 border-t border-[var(--color-line)] pt-3">
          <p className="text-xs font-medium">What you can change</p>
          <ul className="mt-1.5 space-y-1">
            {estimate.remedies.map((remedy) => (
              <li key={remedy} className="text-xs leading-relaxed text-[var(--color-ink-muted)]">
                • {remedy}
              </li>
            ))}
          </ul>
          {onAdjust && estimate.max_safe_seconds > 0 ? (
            <Button
              variant="surface"
              size="sm"
              className="mt-3"
              onClick={() => onAdjust(Math.floor(estimate.max_safe_seconds))}
            >
              <Wand2 className="h-3.5 w-3.5" />
              Set the limit to {formatDuration(Math.floor(estimate.max_safe_seconds))}
            </Button>
          ) : null}
        </div>
      ) : null}

      {!estimate.exact_tokenisation ? (
        <p className="mt-3 text-[11px] leading-relaxed text-[var(--color-warn)]">
          These figures are approximate: {estimate.tokenisation_note}
        </p>
      ) : null}

      {limits && !limits.supports_continuation ? (
        <p className="mt-3 text-[11px] leading-relaxed text-[var(--color-ink-faint)]">
          This runtime generates a song in one pass, so its {limits.context_tokens.toLocaleString()}-token
          window is a hard ceiling — a longer song cannot be assembled from segments.
        </p>
      ) : null}
    </section>
  );
}
