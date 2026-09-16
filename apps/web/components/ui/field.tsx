"use client";

import * as LabelPrimitive from "@radix-ui/react-label";
import * as React from "react";

import { ParameterHelp } from "@/components/ui/parameter-help";
import { cn } from "@/lib/cn";
import type { ParameterGuidance } from "@/types/api";

export const Label = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={cn("text-sm font-medium leading-none text-[var(--color-ink)]", className)}
    {...props}
  />
));
Label.displayName = "Label";

const control = [
  "w-full rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)]",
  "px-3 py-2 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)]",
  "transition-colors duration-[var(--duration-fast)]",
  "hover:border-[var(--color-line-strong)] focus:border-[var(--color-accent)] focus:outline-none",
  "disabled:cursor-not-allowed disabled:opacity-50",
].join(" ");

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

/**
 * The one layout every labelled control uses.
 *
 * Label, help icon, optional value readout, the control, then either the
 * reason it is disabled or its short description. Because every field goes
 * through here, help behaviour is defined once.
 */
export function Field({
  label,
  htmlFor,
  guidance,
  description,
  value,
  disabled,
  disabledReason,
  required,
  error,
  children,
  className,
  actions,
}: {
  label: string;
  htmlFor?: string;
  guidance?: ParameterGuidance | null;
  description?: string;
  value?: React.ReactNode;
  disabled?: boolean;
  disabledReason?: string;
  required?: boolean;
  error?: string | null;
  children: React.ReactNode;
  className?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", disabled && "opacity-60", className)}>
      <div className="flex min-h-5 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <Label htmlFor={htmlFor} className="truncate">
            {label}
            {required ? <span className="ml-0.5 text-[var(--color-accent)]">*</span> : null}
          </Label>
          <ParameterHelp label={label} guidance={guidance} />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {value != null ? (
            <span className="font-mono text-xs tabular-nums text-[var(--color-ink-muted)]">{value}</span>
          ) : null}
          {actions}
        </div>
      </div>
      {children}
      {error ? (
        <p className="text-xs text-[var(--color-danger)]">{error}</p>
      ) : disabled && disabledReason ? (
        <p className="text-xs leading-relaxed text-[var(--color-warn)]">{disabledReason}</p>
      ) : description ? (
        <p className="text-xs leading-relaxed text-[var(--color-ink-faint)]">{description}</p>
      ) : null}
    </div>
  );
}
