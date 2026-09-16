"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";

const button = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-md)] font-medium",
    "transition-[background-color,color,border-color,filter,transform] duration-[var(--duration-fast)]",
    "disabled:pointer-events-none disabled:opacity-45 active:scale-[0.98]",
  ].join(" "),
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--color-accent)] text-[var(--color-accent-ink)] shadow-[var(--shadow-accent)] hover:bg-[var(--color-accent-strong)]",
        surface:
          "border border-[var(--color-line)] bg-[var(--color-surface-2)] text-[var(--color-ink)] hover:border-[var(--color-line-strong)] hover:bg-[var(--color-surface-3)]",
        outline:
          "border border-[var(--color-line)] text-[var(--color-ink)] hover:bg-[var(--color-surface-2)]",
        ghost: "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-ink)]",
        danger:
          "border border-[color-mix(in_oklch,var(--color-danger)_40%,transparent)] bg-[var(--color-danger-soft)] text-[var(--color-danger)] hover:bg-[color-mix(in_oklch,var(--color-danger)_24%,transparent)]",
      },
      size: {
        // Heights are touch-friendly: nothing below 36px, and 44px for the
        // primary action so it is comfortable on a phone.
        xs: "h-8 px-2.5 text-xs",
        sm: "h-9 px-3 text-sm",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "h-9 w-9",
        "icon-sm": "h-8 w-8",
      },
    },
    defaultVariants: { variant: "surface", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Component = asChild ? Slot : "button";
    return (
      <Component
        ref={ref}
        className={cn(button({ variant, size }), className)}
        disabled={asChild ? undefined : disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {asChild ? (
          children
        ) : (
          <>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {children}
          </>
        )}
      </Component>
    );
  },
);
Button.displayName = "Button";

export { button as buttonVariants };
