"use client";

import { MoreHorizontal, Music2, Pencil, Sliders, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { formatRelative } from "@/lib/format";
import { useProjectTarget } from "@/store/project-target";
import type { ProjectSummary } from "@/types/api";

/**
 * One project in the project list.
 *
 * Every action a project supports is on this card: open it, rename it, edit
 * the settings its next take starts from, or delete it. Rename and delete open
 * the shared dialogs, which live in the app shell.
 */
export function ProjectCard({ project }: { project: ProjectSummary }) {
  const request = useProjectTarget((state) => state.request);

  return (
    <Card interactive className="flex h-full flex-col">
      <div className="flex min-w-0 items-start gap-3 p-4">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-surface-2)] text-[var(--color-ink-faint)]">
          <Music2 className="h-4 w-4" />
        </span>

        <div className="min-w-0 flex-1">
          <Link
            href={`/projects/${project.id}`}
            className="block truncate text-sm font-medium hover:text-[var(--color-accent)]"
            title={project.title || "Untitled project"}
          >
            {project.title || "Untitled project"}
          </Link>
          <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-[var(--color-ink-faint)]">
            {project.style || "No style described yet"}
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <Badge tone="outline">{project.mode}</Badge>
            <Badge tone={project.generation_count > 0 ? "accent" : "neutral"}>
              {project.generation_count} version{project.generation_count === 1 ? "" : "s"}
            </Badge>
            <span className="text-[11px] text-[var(--color-ink-faint)]">
              {formatRelative(project.latest_generation_at ?? project.updated_at)}
            </span>
          </div>
        </div>

        <Menu>
          <MenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Actions for ${project.title || "this project"}`}
            >
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </MenuTrigger>
          <MenuContent align="end">
            <MenuItem asChild>
              <Link href={`/projects/${project.id}`}>
                <Music2 className="h-4 w-4" />
                Open project
              </Link>
            </MenuItem>
            <MenuItem asChild>
              <Link href={`/create?project=${project.id}`}>
                <Sparkles className="h-4 w-4" />
                New version
              </Link>
            </MenuItem>
            <MenuSeparator />
            <MenuItem
              onSelect={() => {
                // Let the menu close first: two overlays open at once share
                // one body pointer-events lock, and whichever tears down
                // second can leave it applied.
                requestAnimationFrame(() => request("rename", project));
              }}
            >
              <Pencil className="h-4 w-4" />
              Rename
            </MenuItem>
            <MenuItem asChild>
              <Link href={`/projects/${project.id}/settings`}>
                <Sliders className="h-4 w-4" />
                Edit configuration
              </Link>
            </MenuItem>
            <MenuSeparator />
            <MenuItem
              destructive
              onSelect={() => {
                requestAnimationFrame(() => request("delete", project));
              }}
            >
              <Trash2 className="h-4 w-4" />
              Delete project
            </MenuItem>
          </MenuContent>
        </Menu>
      </div>
    </Card>
  );
}
