"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { api } from "@/lib/api";
import { keys } from "@/hooks/use-queries";
import type { GenerationJob } from "@/types/api";

const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

/**
 * Live job status over server-sent events, with the polling query as the
 * fallback. Every value shown comes from the backend; nothing is interpolated
 * between updates.
 */
export function useGenerationStream(id: string | undefined) {
  const client = useQueryClient();
  const [job, setJob] = React.useState<GenerationJob | null>(null);
  const [connected, setConnected] = React.useState(false);

  React.useEffect(() => {
    if (!id) return;
    const source = new EventSource(api.eventsUrl(id));
    source.onopen = () => setConnected(true);
    source.addEventListener("status", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as GenerationJob;
        setJob(payload);
        client.setQueryData(keys.generation(id), (previous: { generation: GenerationJob; project: unknown } | undefined) =>
          previous ? { ...previous, generation: payload } : previous,
        );
        if (TERMINAL.has(payload.status)) {
          client.invalidateQueries({ queryKey: ["generations"] });
          client.invalidateQueries({ queryKey: keys.queue });
          source.close();
          setConnected(false);
        }
      } catch {
        /* a malformed frame is ignored; the polling query still refreshes */
      }
    });
    source.onerror = () => {
      setConnected(false);
      source.close();
    };
    return () => {
      source.close();
      setConnected(false);
    };
  }, [id, client]);

  return { job, connected };
}
