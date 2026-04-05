"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const DISMISSED_KEY = "pwa-install-dismissed";

type Platform = "android" | "ios" | "unsupported";

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export interface UseInstallPromptReturn {
  /** Whether the install banner can be shown */
  canPrompt: boolean;
  /** Detected platform for install flow */
  platform: Platform;
  /** Trigger the native install dialog (Android only) */
  prompt: () => Promise<void>;
  /** Dismiss the banner permanently */
  dismiss: () => void;
}

function detectIos(): boolean {
  if (typeof window === "undefined") return false;
  const ua = navigator.userAgent;
  const isIos =
    /iPad|iPhone|iPod/.test(ua) ||
    (/Mac/.test(ua) && navigator.maxTouchPoints > 1);
  const isSafari = /Safari/.test(ua) && !/Chrome/.test(ua);
  return isIos && isSafari;
}

function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: minimal-ui)").matches ||
    ("standalone" in navigator &&
      (navigator as unknown as { standalone: boolean }).standalone === true)
  );
}

function isDismissed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem(DISMISSED_KEY) === "true";
  } catch {
    return false;
  }
}

export function useInstallPrompt(): UseInstallPromptReturn {
  const [deferredPrompt, setDeferredPrompt] =
    useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(
    () => isStandalone() || isDismissed()
  );

  // Platform is derived: iOS detected statically, Android confirmed by event
  const platform = useMemo<Platform>(() => {
    if (detectIos()) return "ios";
    if (deferredPrompt) return "android";
    return "unsupported";
  }, [deferredPrompt]);

  useEffect(() => {
    if (dismissed || detectIos()) return;

    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
    };

    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, [dismissed]);

  const prompt = useCallback(async () => {
    if (!deferredPrompt) return;
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === "accepted") {
      setDismissed(true);
    }
    setDeferredPrompt(null);
  }, [deferredPrompt]);

  const dismiss = useCallback(() => {
    localStorage.setItem(DISMISSED_KEY, "true");
    setDismissed(true);
  }, []);

  const canPrompt =
    !dismissed && (platform === "ios" || deferredPrompt !== null);

  return { canPrompt, platform, prompt, dismiss };
}
