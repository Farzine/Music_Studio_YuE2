import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/cn";

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-[var(--radius-full)] px-2.5 py-0.5 text-[11px] font-medium leading-5",
  {
    variants: {
      tone: {
        neutral: "bg-[var(--color-surface-2)] text-[var(--color-ink-muted)]",
        outline: "border border-[var(--color-line)] text-[var(--color-ink-muted)]",
        accent: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
        warn: "bg-[var(--color-warn-soft)] text-[var(--color-warn)]",
        danger: "bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
        info: "bg-[var(--color-info-soft)] text-[var(--color-info)]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}

/** A small dot that carries meaning without relying on colour alone. */
export function StatusDot({ tone = "neutral", label }: { tone?: "accent" | "warn" | "danger" | "neutral"; label: string }) {
  const colour = {
    accent: "bg-[var(--color-accent)]",
    warn: "bg-[var(--color-warn)]",
    danger: "bg-[var(--color-danger)]",
    neutral: "bg-[var(--color-ink-faint)]",
  }[tone];
  return <span className={cn("inline-block h-2 w-2 rounded-full", colour)} role="img" aria-label={label} />;
}
