"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { api } from "@/lib/api";
import type { ConfigObject } from "@/lib/config";

/**
 * Live token budget for the configuration being edited.
 *
 * Debounced, because it follows a slider and a lyrics field. The backend does
 * the counting with the checkpoint's own tokenizer; nothing is estimated here.
 */
export function useBudgetEstimate(config: ConfigObject, enabled = true) {
  const [debounced, setDebounced] = React.useState(config);

  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(config), 350);
    return () => clearTimeout(timer);
  }, [config]);

  const key = JSON.stringify(debounced);
  return useQuery({
    queryKey: ["budget", key],
    queryFn: () => api.estimateBudget(debounced as Record<string, unknown>),
    enabled,
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });
}
