import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/cn";

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium leading-5",
  {
    variants: {
      tone: {
        neutral: "bg-[var(--color-surface-2)] text-[var(--color-ink-muted)]",
        accent: "bg-[color-mix(in_oklch,var(--color-accent)_18%,transparent)] text-[var(--color-accent)]",
        warn: "bg-[color-mix(in_oklch,var(--color-warn)_16%,transparent)] text-[var(--color-warn)]",
        danger: "bg-[color-mix(in_oklch,var(--color-danger)_16%,transparent)] text-[var(--color-danger)]",
        info: "bg-[color-mix(in_oklch,var(--color-info)_16%,transparent)] text-[var(--color-info)]",
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
