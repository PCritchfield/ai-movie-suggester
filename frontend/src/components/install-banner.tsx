"use client";

import { useInstallPrompt } from "@/hooks/use-install-prompt";
import { Button } from "@/components/ui/button";
import { Share, X } from "lucide-react";

/**
 * Platform-aware PWA install banner.
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
              <Share className="inline-block h-4 w-4 align-text-bottom" /> then{" "}
              <strong>&quot;Add to Home Screen&quot;</strong>
            </p>
          ) : (
            <p className="text-sm text-foreground">
              Install AI Movie Suggester for quick access from your home screen.
            </p>
          )}
        </div>

        {platform === "android" && (
          <Button size="sm" onClick={prompt}>
            Install
          </Button>
        )}

        <Button
          variant="ghost"
          size="icon"
          onClick={dismiss}
          aria-label="Dismiss install banner"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
