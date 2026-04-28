"use client";

import { MessageSquare } from "lucide-react";

interface EmptyStateProps {
  onSend: (message: string) => void;
}

const SUGGESTION_CHIPS = [
  "Something like Alien but funny",
  "A good movie for date night",
  "What's the best thriller in my library?",
] as const;

export function EmptyState({ onSend }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4">
      <div className="flex flex-col items-center gap-3 text-center">
        <MessageSquare
          className="h-12 w-12 text-muted-foreground"
          aria-hidden="true"
        />
        <h2 className="text-lg font-semibold">Movie Recommendations</h2>
        <p className="max-w-sm text-sm text-muted-foreground">
          Ask me for movie recommendations from your Jellyfin library
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTION_CHIPS.map((chip) => (
          <button
            key={chip}
            type="button"
            onClick={() => onSend(chip)}
            className="rounded-full border bg-background px-4 py-2 text-sm text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            {chip}
          </button>
        ))}
      </div>
    </div>
  );
}
