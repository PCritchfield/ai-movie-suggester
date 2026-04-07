"use client";

import { X } from "lucide-react";
import type { SearchStatus } from "@/lib/api/types";

interface SearchStatusBannerProps {
  searchStatus: SearchStatus | undefined;
  onDismiss: () => void;
}

const BANNER_TEXT: Record<string, string> = {
  no_embeddings:
    "Your library is being indexed \u2014 recommendations aren\u2019t available yet.",
  partial_embeddings:
    "Your library is still being indexed \u2014 some recommendations may be missing.",
};

export function SearchStatusBanner({
  searchStatus,
  onDismiss,
}: SearchStatusBannerProps) {
  if (!searchStatus || searchStatus === "ok") return null;

  const text = BANNER_TEXT[searchStatus];
  if (!text) return null;

  return (
    <div
      role="status"
      className="flex items-center justify-between border-b bg-muted/50 px-4 py-2 text-sm text-muted-foreground"
    >
      <span>{text}</span>
      <button
        type="button"
        aria-label="Dismiss banner"
        onClick={onDismiss}
        className="ml-2 inline-flex h-6 w-6 items-center justify-center rounded-full hover:bg-accent"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
