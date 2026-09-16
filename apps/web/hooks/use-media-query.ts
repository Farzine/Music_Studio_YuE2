"use client";

import * as React from "react";

/** Subscribes to a media query. Returns false during server rendering. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = React.useState(false);

  React.useEffect(() => {
    const list = window.matchMedia(query);
    setMatches(list.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** True on devices whose primary input can hover, i.e. not touch. */
export function useHasHover(): boolean {
  return useMediaQuery("(hover: hover) and (pointer: fine)");
}

export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 639px)");
}
