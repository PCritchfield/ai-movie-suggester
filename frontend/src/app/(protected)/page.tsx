"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import { useChat } from "@/hooks/use-chat";
import { HeaderContent } from "@/components/chat/header-content";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { EmptyState } from "@/components/chat/empty-state";
import { SearchStatusBanner } from "@/components/chat/search-status-banner";
import type { SearchStatus } from "@/lib/api/types";

export default function ChatPage() {
  const { messages, isStreaming, sendMessage, clearHistory, retry } = useChat();

  // Track banner dismissal state
  const [bannerDismissed, setBannerDismissed] = useState(false);

  // Derive searchStatus from the most recent assistant message
  const latestSearchStatus: SearchStatus | undefined = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant" && messages[i].searchStatus) {
        return messages[i].searchStatus;
      }
    }
    return undefined;
  }, [messages]);

  // Reset banner dismissal when search status transitions (no effect needed)
  const prevSearchStatusRef = useRef(latestSearchStatus);
  if (prevSearchStatusRef.current !== latestSearchStatus) {
    prevSearchStatusRef.current = latestSearchStatus;
    if (bannerDismissed) {
      setBannerDismissed(false);
    }
  }

  // Reset banner dismissed state when a new assistant message arrives with ok status
  const handleNewConversation = useCallback(async () => {
    await clearHistory();
    setBannerDismissed(false);
  }, [clearHistory]);

  const showBanner =
    !bannerDismissed &&
    latestSearchStatus !== undefined &&
    latestSearchStatus !== "ok";

  return (
    <div className="flex flex-col" style={{ height: "100dvh" }}>
      <HeaderContent onNewConversation={handleNewConversation} />
      {showBanner && (
        <SearchStatusBanner
          searchStatus={latestSearchStatus}
          onDismiss={() => setBannerDismissed(true)}
        />
      )}
      {messages.length === 0 ? (
        <EmptyState onSend={sendMessage} />
      ) : (
        <MessageList
          messages={messages}
          isStreaming={isStreaming}
          onRetry={retry}
        />
      )}
      <ChatInput onSend={sendMessage} isStreaming={isStreaming} />
    </div>
  );
}
