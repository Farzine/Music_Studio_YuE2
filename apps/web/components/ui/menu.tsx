"use client";

import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as React from "react";

import { cn } from "@/lib/cn";

export const Menu = DropdownPrimitive.Root;
export const MenuTrigger = DropdownPrimitive.Trigger;

export const MenuContent = React.forwardRef<
  React.ElementRef<typeof DropdownPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DropdownPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <DropdownPrimitive.Portal>
    <DropdownPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      collisionPadding={12}
      className={cn(
        "overlay-content z-50 min-w-48 overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-surface-2)] p-1 shadow-[var(--shadow-lg)]",
        className,
      )}
      {...props}
    />
  </DropdownPrimitive.Portal>
));
MenuContent.displayName = "MenuContent";

export const MenuItem = React.forwardRef<
  React.ElementRef<typeof DropdownPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof DropdownPrimitive.Item> & { destructive?: boolean }
>(({ className, destructive, ...props }, ref) => (
  <DropdownPrimitive.Item
    ref={ref}
    className={cn(
      // 40px tall: a comfortable touch target on a phone.
      "flex h-10 cursor-pointer select-none items-center gap-2.5 rounded-[var(--radius-sm)] px-3 text-sm outline-none transition-colors",
      "data-[highlighted]:bg-[var(--color-surface-3)] data-[disabled]:pointer-events-none data-[disabled]:opacity-45",
      destructive
        ? "text-[var(--color-danger)] data-[highlighted]:bg-[var(--color-danger-soft)]"
        : "text-[var(--color-ink)]",
      className,
    )}
    {...props}
  />
));
MenuItem.displayName = "MenuItem";

export function MenuSeparator({ className }: { className?: string }) {
  return <DropdownPrimitive.Separator className={cn("my-1 h-px bg-[var(--color-line)]", className)} />;
}

export function MenuLabel({ children }: { children: React.ReactNode }) {
  return (
    <DropdownPrimitive.Label className="px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-[var(--color-ink-faint)]">
      {children}
    </DropdownPrimitive.Label>
  );
}
