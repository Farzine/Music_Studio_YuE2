"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/cn";

export default function ModelsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return <div className="space-y-5">
    <nav aria-label="Models" className="flex flex-wrap gap-2 border-b border-[var(--color-line)] pb-3">
      {[["/models", "Installed Models"], ["/models/download", "Download Model"], ["/models/recommended", "Recommended Models"]].map(([href, label]) =>
        <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined}
          className={cn("rounded-[var(--radius-md)] px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]",
            pathname === href ? "bg-[var(--color-accent-soft)] font-medium text-[var(--color-accent)]" : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-2)]")}>{label}</Link>)}
    </nav>
    {children}
  </div>;
}
