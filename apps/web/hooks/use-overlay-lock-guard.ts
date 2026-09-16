"use client";

import { usePathname } from "next/navigation";
import * as React from "react";

/** Selectors for overlays that legitimately hold the body lock while open. */
const OPEN_OVERLAY = [
  '[data-state="open"][role="dialog"]',
  '[data-state="open"][role="alertdialog"]',
  '[data-state="open"][role="menu"]',
  '[data-state="open"][data-radix-popper-content-wrapper]',
  "[data-radix-popper-content-wrapper]",
].join(",");

/**
 * Safety net for a stuck overlay lock.
 *
 * Modal overlays set `pointer-events: none` on the document body and release
 * it on teardown. If one is torn down abruptly — the element that owned it
 * disappearing underneath it, or a navigation mid-close — the release can be
 * skipped, and the page then renders normally while ignoring every click.
 *
 * The real fix is structural: overlays are mounted above whatever they act on
 * (see DeleteGenerationDialogHost). This only catches anything that slips
 * through, and only acts when no overlay is actually open, so it can never
 * unlock the page while a modal is genuinely showing.
 */
export function useOverlayLockGuard(): void {
  const pathname = usePathname();

  React.useEffect(() => {
    const release = () => {
      if (document.body.style.pointerEvents !== "none") return;
      if (document.querySelector(OPEN_OVERLAY)) return;
      document.body.style.removeProperty("pointer-events");
    };

    // After a navigation, and once more on the next frame, by which time any
    // closing overlay has been removed from the DOM.
    release();
    const frame = requestAnimationFrame(release);
    const timer = window.setTimeout(release, 300);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [pathname]);

  React.useEffect(() => {
    // Also recheck whenever the body's inline style changes, which is exactly
    // when the lock is applied or released.
    const observer = new MutationObserver(() => {
      if (document.body.style.pointerEvents !== "none") return;
      if (document.querySelector(OPEN_OVERLAY)) return;
      document.body.style.removeProperty("pointer-events");
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ["style"] });
    return () => observer.disconnect();
  }, []);
}
