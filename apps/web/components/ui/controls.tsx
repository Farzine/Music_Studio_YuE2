"use client";

import * as AccordionPrimitive from "@radix-ui/react-accordion";
import * as SliderPrimitive from "@radix-ui/react-slider";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";

export const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SliderPrimitive.Root
    ref={ref}
    className={cn("relative flex w-full touch-none select-none items-center py-2.5", className)}
    {...props}
  >
    <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-[var(--color-surface-2)]">
      <SliderPrimitive.Range className="absolute h-full bg-[var(--color-accent)]" />
    </SliderPrimitive.Track>
    {/* 18px thumb with a larger invisible hit area: comfortable on touch. */}
    <SliderPrimitive.Thumb className="block h-[18px] w-[18px] rounded-full border-2 border-[var(--color-accent)] bg-[var(--color-canvas)] shadow-[var(--shadow-sm)] transition-transform hover:scale-110 focus-visible:outline-none" />
  </SliderPrimitive.Root>
));
Slider.displayName = "Slider";

export const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      "peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border border-[var(--color-line)] transition-colors data-[state=checked]:bg-[var(--color-accent)] data-[state=unchecked]:bg-[var(--color-surface-2)] disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb className="pointer-events-none block h-4 w-4 translate-x-1 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-6" />
  </SwitchPrimitive.Root>
));
Switch.displayName = "Switch";

export const Accordion = AccordionPrimitive.Root;

export const AccordionItem = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Item>
>(({ className, ...props }, ref) => (
  <AccordionPrimitive.Item
    ref={ref}
    className={cn("border-b border-[var(--color-line)] last:border-b-0", className)}
    {...props}
  />
));
AccordionItem.displayName = "AccordionItem";

export const AccordionTrigger = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <AccordionPrimitive.Header className="flex">
    <AccordionPrimitive.Trigger
      ref={ref}
      className={cn(
        "group flex min-h-12 flex-1 items-center justify-between gap-3 py-3.5 text-left text-sm font-medium transition-colors hover:text-[var(--color-accent)]",
        className,
      )}
      {...props}
    >
      {children}
      <ChevronDown className="h-4 w-4 shrink-0 opacity-60 transition-transform group-data-[state=open]:rotate-180" />
    </AccordionPrimitive.Trigger>
  </AccordionPrimitive.Header>
));
AccordionTrigger.displayName = "AccordionTrigger";

export const AccordionContent = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <AccordionPrimitive.Content
    ref={ref}
    className="accordion-content overflow-hidden"
    {...props}
  >
    <div className={cn("pb-5 pt-1", className)}>{children}</div>
  </AccordionPrimitive.Content>
));
AccordionContent.displayName = "AccordionContent";

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex items-center gap-1 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-surface)] p-1",
      className,
    )}
    {...props}
  />
));
TabsList.displayName = "TabsList";

export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "rounded-[var(--radius-sm)] px-3 py-2 text-sm text-[var(--color-ink-muted)] transition-colors data-[state=active]:bg-[var(--color-surface-3)] data-[state=active]:text-[var(--color-ink)]",
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = "TabsTrigger";

export const TabsContent = TabsPrimitive.Content;

export const TooltipProvider = TooltipPrimitive.Provider;

export function Tooltip({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <TooltipPrimitive.Root delayDuration={200}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="popover-content z-50 max-w-xs rounded-[var(--radius-sm)] border border-[var(--color-line)] bg-[var(--color-surface-2)] px-3 py-2 text-xs leading-relaxed text-[var(--color-ink-muted)] shadow-[var(--shadow-lg)]"
        >
          {label}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
