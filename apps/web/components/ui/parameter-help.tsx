"use client";

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { CircleAlert, Info, X } from "lucide-react";
import * as React from "react";

import { Sheet } from "@/components/ui/sheet";
import { useHasHover, useIsMobile } from "@/hooks/use-media-query";
import { cn } from "@/lib/cn";
import type { ParameterGuidance } from "@/types/api";

/**
 * The single help affordance used by every parameter in the application.
 *
 * One implementation covers all three interaction models the product needs:
 * hover on a pointer device, tap on touch, and keyboard focus. Below the
 * mobile breakpoint the same content opens as a bottom sheet, because a
 * popover anchored to a 16px icon is unusable on a phone.
 *
 * The icon is semantic: ⓘ for ordinary information, ⚠ only where an unusual
 * value genuinely destabilises output, inflates VRAM or lengthens a run.
 */

const ROWS: { key: keyof ParameterGuidance; label: string }[] = [
  { key: "more", label: "Higher" },
  { key: "less", label: "Lower" },
  { key: "recommended", label: "Recommended" },
  { key: "extremes", label: "At extremes" },
  { key: "cost", label: "Time and memory" },
];

export function ParameterHelpBody({
  label,
  guidance,
  className,
}: {
  label: string;
  guidance: ParameterGuidance;
  className?: string;
}) {
  const rows = ROWS.filter((row) => Boolean(guidance[row.key]));
  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-start gap-2">
        {guidance.severity === "caution" ? (
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warn)]" />
        ) : (
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-info)]" />
        )}
        <p className="text-sm font-semibold leading-snug text-[var(--color-ink)]">{label}</p>
      </div>
      <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">{guidance.what}</p>
      {rows.length > 0 ? (
        <dl className="space-y-2 border-t border-[var(--color-line)] pt-3">
          {rows.map((row) => (
            <div key={row.key} className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3">
              <dt className="text-xs font-medium uppercase tracking-wide text-[var(--color-ink-faint)]">
                {row.label}
              </dt>
              <dd className="text-xs leading-relaxed text-[var(--color-ink-muted)]">
                {guidance[row.key]}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

export function ParameterHelp({
  label,
  guidance,
  className,
}: {
  label: string;
  guidance?: ParameterGuidance | null;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [pinned, setPinned] = React.useState(false);
  const hasHover = useHasHover();
  const isMobile = useIsMobile();
  const closeTimer = React.useRef<number | null>(null);

  if (!guidance) return null;

  const caution = guidance.severity === "caution";
  const Icon = caution ? CircleAlert : Info;
  const triggerLabel = `${caution ? "Caution" : "About"}: ${label}`;

  const trigger = (
    <button
      type="button"
      aria-label={triggerLabel}
      className={cn(
        "inline-grid h-5 w-5 shrink-0 place-items-center rounded-full text-[var(--color-ink-faint)] transition-colors",
        "hover:bg-[var(--color-surface-2)] hover:text-[var(--color-ink)]",
        caution && "text-[var(--color-warn)] hover:text-[var(--color-warn)]",
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
    </button>
  );

  // Phones get a bottom sheet: a popover pinned to a 16px target is not usable.
  if (isMobile) {
    return (
      <>
        {React.cloneElement(trigger, { onClick: () => setOpen(true) })}
        <Sheet open={open} onOpenChange={setOpen} title={label}>
          <ParameterHelpBody label={label} guidance={guidance} />
        </Sheet>
      </>
    );
  }

  const cancelClose = () => {
    if (closeTimer.current) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };
  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => {
      if (!pinned) setOpen(false);
    }, 120);
  };

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setPinned(false);
      }}
    >
      <PopoverPrimitive.Trigger asChild>
        {React.cloneElement(trigger, {
          onPointerEnter: hasHover ? () => { cancelClose(); setOpen(true); } : undefined,
          onPointerLeave: hasHover ? scheduleClose : undefined,
          onFocus: () => setOpen(true),
          onBlur: () => { if (!pinned) setOpen(false); },
          onClick: (event: React.MouseEvent) => {
            event.preventDefault();
            setPinned((value) => !value);
            setOpen(true);
          },
        })}
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="top"
          align="start"
          sideOffset={8}
          collisionPadding={16}
          // Never cover the control the help is about.
          avoidCollisions
          onOpenAutoFocus={(event) => event.preventDefault()}
          onPointerEnter={hasHover ? cancelClose : undefined}
          onPointerLeave={hasHover ? scheduleClose : undefined}
          className="popover-content z-50 w-[min(22rem,calc(100vw-2rem))] rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-surface-2)] p-4 shadow-[var(--shadow-lg)]"
        >
          <ParameterHelpBody label={label} guidance={guidance} />
          <PopoverPrimitive.Arrow className="fill-[var(--color-surface-2)]" />
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

export { X as HelpCloseIcon };
