import * as React from "react";

import { cn } from "@/lib/cn";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("skeleton rounded-[var(--radius-md)]", className)} {...props} />;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-[var(--radius-lg)] border border-dashed border-[var(--color-line)] px-6 py-12 text-center sm:py-16",
        className,
      )}
    >
      {icon ? <div className="text-[var(--color-ink-faint)]">{icon}</div> : null}
      <div className="space-y-1">
        <p className="text-sm font-medium text-[var(--color-ink)]">{title}</p>
        {description ? (
          <p className="mx-auto max-w-md text-sm text-[var(--color-ink-faint)]">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorNotice({
  title,
  message,
  guidance,
  actions,
  details,
  className,
}: {
  title?: string;
  message: string;
  guidance?: string | null;
  actions?: React.ReactNode;
  details?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-[var(--radius-md)] border border-[color-mix(in_oklch,var(--color-danger)_35%,transparent)] bg-[var(--color-danger-soft)] px-4 py-3",
        className,
      )}
    >
      {title ? (
        <p className="text-sm font-semibold capitalize text-[var(--color-danger)]">{title}</p>
      ) : null}
      <p className="text-sm leading-relaxed text-[var(--color-ink)]">{message}</p>
      {guidance ? (
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-ink-muted)]">{guidance}</p>
      ) : null}
      {actions ? <div className="mt-3 flex flex-wrap gap-2">{actions}</div> : null}
      {details ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]">
            Technical details
          </summary>
          <div className="mt-2 max-h-52 overflow-auto rounded-[var(--radius-sm)] bg-[var(--color-canvas)] p-2 font-mono text-[11px] leading-relaxed text-[var(--color-ink-muted)]">
            {details}
          </div>
        </details>
      ) : null}
    </div>
  );
}

export function WarningNotice({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-md)] border border-[color-mix(in_oklch,var(--color-warn)_32%,transparent)] bg-[var(--color-warn-soft)] px-4 py-3 text-sm leading-relaxed text-[var(--color-ink)]",
        className,
      )}
    >
      {children}
    </div>
  );
}
