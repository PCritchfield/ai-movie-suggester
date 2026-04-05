"use client";

import { useInstallPrompt } from "@/hooks/use-install-prompt";
import { X } from "lucide-react";

/**
 * Platform-aware PWA install banner.
 *
 * Mount this component in the protected layout after the Chat UI spec
 * wires the trigger timing. See issue #138 for the deferred trigger wiring.
 *
 * - Android/Chrome: Captures `beforeinstallprompt` and triggers native dialog
 * - iOS Safari: Shows manual "Add to Home Screen" instructions
 * - Dismissed once → never shown again (localStorage)
 */
export function InstallBanner() {
  const { canPrompt, platform, prompt, dismiss } = useInstallPrompt();

  if (!canPrompt) return null;

  return (
    <div
      role="banner"
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-card p-4 shadow-lg"
    >
      <div className="mx-auto flex max-w-lg items-center gap-3">
        <div className="flex-1">
          {platform === "ios" ? (
            <p className="text-sm text-foreground">
              Install this app: tap{" "}
              <ShareIcon className="inline-block h-4 w-4 align-text-bottom" />{" "}
              then <strong>&quot;Add to Home Screen&quot;</strong>
            </p>
          ) : (
            <p className="text-sm text-foreground">
              Install AI Movie Suggester for quick access from your home screen.
            </p>
          )}
        </div>

        {platform === "android" && (
          <button
            type="button"
            onClick={prompt}
            className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
          >
            Install
          </button>
        )}

        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss install banner"
          className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

/** Inline Safari share icon (square with arrow) */
function ShareIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
      <polyline points="16 6 12 2 8 6" />
      <line x1="12" y1="2" x2="12" y2="15" />
    </svg>
  );
}
