"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all disabled:pointer-events-none disabled:opacity-45 active:scale-[0.985] whitespace-nowrap",
  {
    variants: {
      variant: {
        primary: "bg-[var(--color-accent)] text-[var(--color-accent-ink)] hover:brightness-110 shadow-lg shadow-[color-mix(in_oklch,var(--color-accent)_25%,transparent)]",
        surface: "bg-[var(--color-surface-2)] text-[var(--color-ink)] hover:bg-[color-mix(in_oklch,var(--color-surface-2)_80%,var(--color-ink)_8%)] border border-[var(--color-line)]",
        ghost: "text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] hover:bg-[var(--color-surface-2)]",
        danger: "bg-[color-mix(in_oklch,var(--color-danger)_18%,transparent)] text-[var(--color-danger)] border border-[color-mix(in_oklch,var(--color-danger)_35%,transparent)] hover:bg-[color-mix(in_oklch,var(--color-danger)_26%,transparent)]",
        outline: "border border-[var(--color-line)] text-[var(--color-ink)] hover:bg-[var(--color-surface-2)]",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "surface", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, ...props }, ref) => {
    const Component = asChild ? Slot : "button";
    return <Component ref={ref} className={cn(button({ variant, size }), className)} {...props} />;
  },
);
Button.displayName = "Button";
