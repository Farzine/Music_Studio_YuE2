"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";

/** Bottom sheet. Focus is trapped and Escape closes, via Radix Dialog. */
export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="animate-fade-in fixed inset-0 z-50 bg-[var(--color-overlay)] backdrop-blur-sm" />
        <DialogPrimitive.Content
          className={cn(
            "animate-sheet-up fixed inset-x-0 bottom-0 z-50 max-h-[85dvh] overflow-y-auto rounded-t-[var(--radius-xl)] border-t border-[var(--color-line)] bg-[var(--color-surface)] pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-[var(--shadow-lg)]",
            className,
          )}
        >
          <div className="sticky top-0 flex items-start justify-between gap-3 bg-[var(--color-surface)] px-5 pb-3 pt-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="truncate text-sm font-semibold">{title}</DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="mt-0.5 text-xs text-[var(--color-ink-faint)]">
                  {description}
                </DialogPrimitive.Description>
              ) : null}
            </div>
            <DialogPrimitive.Close
              aria-label="Close"
              className="-mr-1 grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius-sm)] text-[var(--color-ink-faint)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-ink)]"
            >
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>
          <div className="px-5">{children}</div>
          {/* A grab handle reads as "draggable"; this sheet is tap-to-close. */}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
