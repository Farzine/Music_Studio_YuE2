"use client";

import {
  CircleAlert,
  Cpu,
  Disc3,
  FolderOpen,
  Info,
  Library,
  Settings,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { DeleteGenerationDialogHost } from "@/components/library/delete-generation-dialog";
import { GenerationDialogHost } from "@/components/library/generation-dialogs";
import { ProjectDialogHost } from "@/components/projects/project-dialogs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PlayerBar } from "@/features/player/player-bar";
import { QueueDrawer } from "@/features/queue/queue-drawer";
import { useOverlayLockGuard } from "@/hooks/use-overlay-lock-guard";
import { useHealth, useQueue } from "@/hooks/use-queries";
import { cn } from "@/lib/cn";
import { usePlayer } from "@/store/player";

const NAV = [
  { href: "/create", label: "Create", icon: Sparkles },
  { href: "/library", label: "Library", icon: Library },
  { href: "/projects", label: "Projects", icon: FolderOpen },
  { href: "/system", label: "System", icon: Cpu },
  { href: "/settings", label: "Settings", icon: Settings },
];

const SECONDARY = [{ href: "/about", label: "About", icon: Info }];

function useIsActive() {
  const pathname = usePathname();
  return React.useCallback(
    (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href)),
    [pathname],
  );
}

function HealthBadge() {
  const { data } = useHealth();
  if (!data) return null;
  if (data.ready) {
    return (
      <Badge tone="accent" title={`Backend: ${data.backend}`}>
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
        {data.backend}
      </Badge>
    );
  }
  return (
    <Link href="/system">
      <Badge tone="warn">
        <CircleAlert className="h-3 w-3" />
        {data.worker_online ? "model missing" : "worker offline"}
      </Badge>
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const isActive = useIsActive();
  const { data: queue } = useQueue();
  const track = usePlayer((state) => state.track);
  const busy = (queue?.active.length ?? 0) + (queue?.depth ?? 0);
  useOverlayLockGuard();

  return (
    <div className="min-h-dvh">
      {/* Header: one row on every size. */}
      <header className="sticky top-0 z-30 border-b border-[var(--color-line)] bg-[color-mix(in_oklch,var(--color-canvas)_88%,transparent)] backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1800px] items-center gap-3 px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5" aria-label="YuE2 Music Studio home">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius-md)] bg-[var(--color-accent)] text-[var(--color-accent-ink)]">
              <Disc3 className="h-5 w-5" />
            </span>
            <span className="hidden text-sm font-semibold tracking-tight sm:block">YuE2 Music Studio</span>
          </Link>

          <div className="ml-auto flex items-center gap-2">
            <HealthBadge />
            <Button variant="primary" size="sm" asChild className="lg:hidden">
              <Link href="/create">
                <Sparkles className="h-4 w-4" />
                <span className="sr-only sm:not-sr-only">Create</span>
              </Link>
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-[1800px]">
        {/* Desktop sidebar. */}
        <aside className="sticky top-16 hidden h-[calc(100dvh-4rem)] w-[var(--sidebar-width)] shrink-0 border-r border-[var(--color-line)] px-3 py-5 lg:block">
          <Button variant="primary" className="mb-4 w-full" asChild>
            <Link href="/create">
              <Sparkles className="h-4 w-4" />
              Create
            </Link>
          </Button>
          <nav aria-label="Main" className="space-y-1">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-10 items-center gap-3 rounded-[var(--radius-md)] px-3 text-sm transition-colors",
                    active
                      ? "bg-[var(--color-surface-2)] font-medium text-[var(--color-ink)]"
                      : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface)] hover:text-[var(--color-ink)]",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="truncate">{item.label}</span>
                  {item.href === "/library" && busy > 0 ? (
                    <Badge tone="accent" className="ml-auto">
                      {busy}
                    </Badge>
                  ) : null}
                </Link>
              );
            })}
          </nav>
          <div className="mt-6 border-t border-[var(--color-line)] pt-4">
            {SECONDARY.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="flex h-9 items-center gap-3 rounded-[var(--radius-md)] px-3 text-sm text-[var(--color-ink-faint)] transition-colors hover:text-[var(--color-ink)]"
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </aside>

        <main
          className="min-w-0 flex-1 px-4 py-5 sm:px-6 sm:py-6"
          style={{
            // Room for the mobile nav and the player, whichever are showing.
            paddingBottom: `calc(1.5rem + var(--mobile-nav-height) + ${track ? "var(--player-height)" : "0px"} + env(safe-area-inset-bottom))`,
          }}
        >
          {children}
        </main>
      </div>

      <QueueDrawer />
      <PlayerBar />
      {/* Mounted once, above everything they can act on. A dialog rendered
          inside a card would unmount at the moment its card disappears, and an
          open overlay that unmounts leaves the page unclickable. */}
      <DeleteGenerationDialogHost />
      <GenerationDialogHost />
      <ProjectDialogHost />

      {/* Mobile navigation, above the player. */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-[var(--color-line)] bg-[color-mix(in_oklch,var(--color-canvas)_95%,transparent)] pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
        style={{ marginBottom: track ? "var(--player-height)" : undefined }}
      >
        <div className="flex items-stretch justify-around">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-[var(--mobile-nav-height)] flex-1 flex-col items-center justify-center gap-1 text-[11px] transition-colors",
                  active ? "text-[var(--color-accent)]" : "text-[var(--color-ink-faint)]",
                )}
              >
                <Icon className="h-5 w-5" />
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
