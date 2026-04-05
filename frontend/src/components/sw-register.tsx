"use client";

import { useEffect } from "react";

/**
 * Registers the service worker on mount. Renders nothing.
 * Skipped in development to avoid stale-cache confusion.
 */
export function SwRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;

    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("SW registration failed:", err);
    });
  }, []);

  return null;
}
