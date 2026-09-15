import * as React from "react";

import { cn } from "@/lib/cn";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("skeleton rounded-xl", className)} {...props} />;
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
        "flex flex-col items-center justify-center gap-3 rounded-[var(--radius-card)] border border-dashed border-[var(--color-line)] px-6 py-14 text-center",
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
  className,
}: {
  title?: string;
  message: string;
  guidance?: string | null;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-xl border border-[color-mix(in_oklch,var(--color-danger)_35%,transparent)] bg-[color-mix(in_oklch,var(--color-danger)_10%,transparent)] px-4 py-3",
        className,
      )}
    >
      {title ? <p className="text-sm font-semibold text-[var(--color-danger)]">{title}</p> : null}
      <p className="text-sm text-[var(--color-ink)]">{message}</p>
      {guidance ? <p className="mt-1 text-xs text-[var(--color-ink-muted)]">{guidance}</p> : null}
    </div>
  );
}

export function WarningNotice({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-[color-mix(in_oklch,var(--color-warn)_32%,transparent)] bg-[color-mix(in_oklch,var(--color-warn)_9%,transparent)] px-4 py-3 text-sm text-[var(--color-ink)]",
        className,
      )}
    >
      {children}
    </div>
  );
}
