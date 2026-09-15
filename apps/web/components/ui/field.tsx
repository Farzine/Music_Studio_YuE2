"use client";

import * as LabelPrimitive from "@radix-ui/react-label";
import * as React from "react";

import { cn } from "@/lib/cn";

export const Label = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={cn("text-sm font-medium text-[var(--color-ink)]", className)}
    {...props}
  />
));
Label.displayName = "Label";

const control =
  "w-full rounded-xl border border-[var(--color-line)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)] transition-colors focus:border-[var(--color-accent)] disabled:opacity-50";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn(control, "h-10", className)} {...props} />,
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(control, "resize-y leading-relaxed", className)} {...props} />
));
Textarea.displayName = "Textarea";

export function FieldShell({
  label,
  help,
  htmlFor,
  hint,
  disabled,
  disabledReason,
  children,
  className,
}: {
  label: string;
  help?: string;
  htmlFor?: string;
  hint?: React.ReactNode;
  disabled?: boolean;
  disabledReason?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", disabled && "opacity-60", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <Label htmlFor={htmlFor}>{label}</Label>
        {hint ? <span className="text-xs tabular-nums text-[var(--color-ink-faint)]">{hint}</span> : null}
      </div>
      {children}
      {disabled && disabledReason ? (
        <p className="text-xs text-[var(--color-warn)]">{disabledReason}</p>
      ) : help ? (
        <p className="text-xs leading-relaxed text-[var(--color-ink-faint)]">{help}</p>
      ) : null}
    </div>
  );
}
