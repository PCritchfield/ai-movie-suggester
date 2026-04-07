"use client";

import { useAuth } from "@/lib/auth/auth-context";
import { LogoutButton } from "@/components/logout-button";

interface HeaderContentProps {
  onNewConversation?: () => void;
}

export function HeaderContent({ onNewConversation }: HeaderContentProps) {
  const { username } = useAuth();

  return (
    <div className="flex h-12 items-center justify-between border-b px-4">
      <span className="text-sm font-semibold">ai-movie-suggester</span>
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">{username}</span>
        {onNewConversation && (
          <button
            type="button"
            aria-label="Start new conversation"
            onClick={onNewConversation}
            className="inline-flex min-h-11 items-center justify-center rounded-md px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
          >
            New chat
          </button>
        )}
        <LogoutButton />
      </div>
    </div>
  );
}
