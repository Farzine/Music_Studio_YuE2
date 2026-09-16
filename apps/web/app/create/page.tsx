"use client";

import { Library } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { CreateForm } from "@/features/create/create-form";
import { GenerationCard } from "@/components/library/generation-card";
import { useGenerations } from "@/hooks/use-queries";

export default function CreatePage() {
  const { data, isLoading } = useGenerations({ limit: 12 });

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="min-w-0">
        <CreateForm />
      </div>

      <aside className="min-w-0 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Recent generations</h2>
          <Button variant="ghost" size="sm" asChild>
            <Link href="/library">
              <Library className="h-3.5 w-3.5" />
              Library
            </Link>
          </Button>
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-28 w-full" />
            ))}
          </div>
        ) : data && data.items.length > 0 ? (
          <div className="space-y-3">
            {data.items.map((job) => (
              <GenerationCard key={job.id} job={job} />
            ))}
          </div>
        ) : (
          <EmptyState
            title="Nothing here yet"
            description="Describe a style, write a few lines, and press Create. Your songs will appear here."
          />
        )}
      </aside>
    </div>
  );
}
