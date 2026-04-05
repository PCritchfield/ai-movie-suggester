"use client";

import { useCallback, useEffect, useState } from "react";

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

function detectPlatform(): Platform {
  if (typeof window === "undefined") return "unsupported";

  const ua = navigator.userAgent;
  const isIos =
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isSafari = /Safari/.test(ua) && !/Chrome/.test(ua);

  if (isIos && isSafari) return "ios";

  // Android Chrome or desktop Chrome — beforeinstallprompt capable
  if ("BeforeInstallPromptEvent" in window) return "android";

  return "unsupported";
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
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(DISMISSED_KEY) === "true";
}

export function useInstallPrompt(): UseInstallPromptReturn {
  const [deferredPrompt, setDeferredPrompt] =
    useState<BeforeInstallPromptEvent | null>(null);
  const [platform, setPlatform] = useState<Platform>(() => detectPlatform());
  const [dismissed, setDismissed] = useState(() => isStandalone() || isDismissed());

  useEffect(() => {
    if (dismissed) return;

    if (platform === "ios") return;

    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
      setPlatform("android");
    };

    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, [dismissed, platform]);

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
