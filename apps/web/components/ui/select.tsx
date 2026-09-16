"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "flex h-10 w-full items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-canvas)] px-3 text-left text-sm transition-colors hover:border-[var(--color-line-strong)] focus:border-[var(--color-accent)] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-[var(--color-ink-faint)]",
      className,
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className="h-4 w-4 opacity-60" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = "SelectTrigger";

export const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      position={position}
      className={cn(
        "overlay-content z-50 max-h-[min(24rem,60dvh)] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-surface-2)] shadow-[var(--shadow-lg)]",
        className,
      )}
      {...props}
    >
      <SelectPrimitive.Viewport className="max-h-[min(24rem,60dvh)] overflow-y-auto p-1">
        {children}
      </SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = "SelectContent";

/**
 * A select option.
 *
 * Radix reserves the empty string for "no selection", and throws if an item
 * uses it. Guarding here turns what was a blank-screen crash into a loud,
 * findable development error.
 */
export const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & { help?: string }
>(({ className, children, help, value, ...props }, ref) => {
  if (process.env.NODE_ENV !== "production" && value === "") {
    throw new Error("SelectItem needs a non-empty value; use an explicit sentinel such as 'default'.");
  }
  return (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex min-h-10 cursor-pointer select-none flex-col justify-center gap-0.5 rounded-[var(--radius-sm)] px-3 py-2 pr-8 text-sm outline-none data-[highlighted]:bg-[var(--color-surface-3)] data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45",
      className,
    )}
      value={value}
      {...props}
    >
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      {help ? <span className="text-xs leading-snug text-[var(--color-ink-faint)]">{help}</span> : null}
      <SelectPrimitive.ItemIndicator className="absolute right-2 top-3">
        <Check className="h-4 w-4 text-[var(--color-accent)]" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
});
SelectItem.displayName = "SelectItem";
