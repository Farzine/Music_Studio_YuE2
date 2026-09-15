"use client";

import {
  CircleAlert,
  Cpu,
  Disc3,
  Folder,
  Info,
  Library,
  Settings,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { PlayerBar } from "@/features/player/player-bar";
import { QueueDrawer } from "@/features/queue/queue-drawer";
import { useHealth } from "@/hooks/use-queries";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/create", label: "Create", icon: Sparkles },
  { href: "/library", label: "Library", icon: Library },
  { href: "/", label: "Projects", icon: Folder },
  { href: "/system", label: "System", icon: Cpu },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/about", label: "About", icon: Info },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: health } = useHealth();

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <div className="min-h-dvh pb-40 lg:pb-28">
      <header className="sticky top-0 z-30 border-b border-[var(--color-line)] bg-[color-mix(in_oklch,var(--color-canvas)_88%,transparent)] backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-2 px-4 sm:px-6">
          <Link href="/" className="mr-2 flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--color-accent)] text-[var(--color-accent-ink)]">
              <Disc3 className="h-5 w-5" />
            </span>
            <span className="hidden text-sm font-semibold tracking-tight sm:block">YuE2 Music Studio</span>
          </Link>

          <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-xl px-3 py-2 text-sm transition-colors",
                  isActive(item.href)
                    ? "bg-[var(--color-surface-2)] text-[var(--color-ink)]"
                    : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface)] hover:text-[var(--color-ink)]",
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {health ? (
              health.ready ? (
                <Badge tone="accent">
                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                  {health.backend}
                </Badge>
              ) : (
                <Link href="/system">
                  <Badge tone="warn">
                    <CircleAlert className="h-3 w-3" />
                    {health.worker_online ? "model missing" : "worker offline"}
                  </Badge>
                </Link>
              )
            ) : null}
            <Link
              href="/create"
              className="rounded-xl bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-[var(--color-accent-ink)] transition-[filter] hover:brightness-110"
            >
              Create
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6">{children}</main>

      {/* Mobile navigation sits above the player. */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-[4.5rem] z-30 border-t border-[var(--color-line)] bg-[color-mix(in_oklch,var(--color-canvas)_94%,transparent)] backdrop-blur-xl lg:hidden"
      >
        <div className="flex items-stretch justify-around">
          {NAV.slice(0, 5).map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px]",
                  isActive(item.href) ? "text-[var(--color-accent)]" : "text-[var(--color-ink-faint)]",
                )}
              >
                <Icon className="h-4.5 w-4.5" />
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>

      <QueueDrawer />
      <PlayerBar />
    </div>
  );
}
