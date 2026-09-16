import * as React from "react";

import { cn } from "@/lib/cn";

export function Card({
  className,
  interactive,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-surface)]",
        interactive &&
          "transition-[border-color,background-color] duration-[var(--duration-base)] hover:border-[var(--color-line-strong)] hover:bg-[var(--color-surface-2)]",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 p-5 pb-3 sm:p-6 sm:pb-4", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-base font-semibold tracking-tight", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm leading-relaxed text-[var(--color-ink-muted)]", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 pt-0 sm:p-6 sm:pt-0", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-wrap items-center gap-2 p-5 pt-0 sm:p-6 sm:pt-0", className)} {...props} />;
}

/** Section heading used inside settings panels and detail pages. */
export function SectionHeading({
  title,
  description,
  action,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="min-w-0 space-y-1">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {description ? (
          <p className="text-xs leading-relaxed text-[var(--color-ink-faint)]">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
