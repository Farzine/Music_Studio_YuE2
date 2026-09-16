"use client";

import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";

const overlay =
  "animate-fade-in fixed inset-0 z-50 bg-[var(--color-overlay)] backdrop-blur-sm";
const panel =
  "overlay-content fixed left-1/2 top-1/2 z-50 w-[min(34rem,calc(100vw-2rem))] max-h-[85dvh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-surface)] p-6 shadow-[var(--shadow-lg)]";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlay} />
        <DialogPrimitive.Content className={cn(panel, className)}>
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 space-y-1">
              <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="text-sm text-[var(--color-ink-muted)]">
                  {description}
                </DialogPrimitive.Description>
              ) : null}
            </div>
            <DialogPrimitive.Close
              aria-label="Close"
              className="-mr-2 -mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-[var(--radius-sm)] text-[var(--color-ink-faint)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-ink)]"
            >
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>
          {children ? <div className="mt-4">{children}</div> : null}
          {footer ? <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div> : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/**
 * Confirmation for an action that cannot be undone.
 *
 * Uses AlertDialog rather than Dialog: it traps focus on the safe action and
 * cannot be dismissed by clicking away, so a destructive step is always a
 * deliberate one.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  details,
  confirmLabel = "Delete",
  cancelLabel = "Cancel",
  destructive = true,
  busy = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  details?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  return (
    <AlertDialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialogPrimitive.Portal>
        <AlertDialogPrimitive.Overlay className={overlay} />
        <AlertDialogPrimitive.Content className={cn(panel, "w-[min(30rem,calc(100vw-2rem))]")}>
          <AlertDialogPrimitive.Title className="text-base font-semibold">{title}</AlertDialogPrimitive.Title>
          {description ? (
            <AlertDialogPrimitive.Description className="mt-2 text-sm leading-relaxed text-[var(--color-ink-muted)]">
              {description}
            </AlertDialogPrimitive.Description>
          ) : null}
          {details ? (
            <div className="mt-4 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] p-3 text-sm text-[var(--color-ink-muted)]">
              {details}
            </div>
          ) : null}
          <div className="mt-6 flex flex-wrap justify-end gap-2">
            <AlertDialogPrimitive.Cancel asChild>
              <button
                type="button"
                className="h-10 rounded-[var(--radius-md)] border border-[var(--color-line)] px-4 text-sm transition-colors hover:bg-[var(--color-surface-2)]"
              >
                {cancelLabel}
              </button>
            </AlertDialogPrimitive.Cancel>
            <AlertDialogPrimitive.Action asChild>
              <button
                type="button"
                disabled={busy}
                onClick={(event) => {
                  event.preventDefault();
                  void onConfirm();
                }}
                className={cn(
                  "h-10 rounded-[var(--radius-md)] px-4 text-sm font-medium transition-[filter] disabled:opacity-50",
                  destructive
                    ? "bg-[var(--color-danger)] text-white hover:brightness-110"
                    : "bg-[var(--color-accent)] text-[var(--color-accent-ink)] hover:brightness-110",
                )}
              >
                {busy ? "Working…" : confirmLabel}
              </button>
            </AlertDialogPrimitive.Action>
          </div>
        </AlertDialogPrimitive.Content>
      </AlertDialogPrimitive.Portal>
    </AlertDialogPrimitive.Root>
  );
}
