"use client";

import React, { useEffect, useRef, useCallback, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import type {
  ChatMessage,
  ChatErrorCode,
  SearchResultItem,
} from "@/lib/api/types";
import { CardCarousel } from "./card-carousel";
import { CardDetail } from "./card-detail";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  onRetry?: (messageId: string) => void;
  onCardClick?: (item: SearchResultItem) => void;
}

/** Dots animation for streaming loading state */
function LoadingIndicator() {
  return (
    <div
      className="flex items-center gap-1 px-4 py-2"
      aria-label="Loading response"
    >
      <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:0ms]" />
      <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:150ms]" />
      <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:300ms]" />
    </div>
  );
}

/** Inline error display with retry/login link */
function MessageError({
  error,
  messageId,
  onRetry,
}: {
  error: { code: ChatErrorCode; message: string };
  messageId: string;
  onRetry?: (messageId: string) => void;
}) {
  const is401 = error.code === "auth_expired";
  const is429 = error.code === "rate_limited";

  return (
    <div role="alert" className="mt-2 text-sm text-destructive">
      <p>{error.message}</p>
      <div className="mt-1 flex items-center gap-2">
        {is401 ? (
          <a
            href="/login?reason=session_expired"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/20"
          >
            Log in again
          </a>
        ) : (
          onRetry && (
            <RetryButton
              messageId={messageId}
              onRetry={onRetry}
              is429={is429}
            />
          )
        )}
      </div>
    </div>
  );
}

/** Retry button with optional 429 cooldown */
function RetryButton({
  messageId,
  onRetry,
  is429,
}: {
  messageId: string;
  onRetry: (messageId: string) => void;
  is429: boolean;
}) {
  const [disabled, setDisabled] = React.useState(is429);

  React.useEffect(() => {
    if (is429) {
      setDisabled(true);
      const timer = setTimeout(() => setDisabled(false), 10000);
      return () => clearTimeout(timer);
    }
  }, [is429]);

  return (
    <button
      type="button"
      aria-label="Retry message"
      disabled={disabled}
      onClick={() => onRetry(messageId)}
      className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/20 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {disabled ? "Try again in a moment" : "Retry"}
    </button>
  );
}

export function MessageList({
  messages,
  isStreaming,
  onRetry,
  onCardClick,
}: MessageListProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);
  const [selectedMovie, setSelectedMovie] = useState<SearchResultItem | null>(
    null
  );

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const threshold = 50;
    userScrolledUpRef.current =
      el.scrollTop + el.clientHeight < el.scrollHeight - threshold;
  }, []);

  // Auto-scroll to bottom on new messages/streaming updates
  useEffect(() => {
    if (userScrolledUpRef.current) return;
    const el = scrollContainerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  return (
    <div
      ref={scrollContainerRef}
      onScroll={handleScroll}
      role="log"
      aria-live="polite"
      aria-busy={isStreaming}
      className="flex-1 overflow-y-auto px-4 py-4"
    >
      <div className="mx-auto max-w-3xl space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-foreground"
              }`}
            >
              {msg.role === "assistant" ? (
                <>
                  {msg.isStreaming && !msg.content ? (
                    <LoadingIndicator />
                  ) : (
                    <div className="prose prose-sm dark:prose-invert max-w-none break-words">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        rehypePlugins={[rehypeSanitize]}
                      >
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  )}
                  {msg.recommendations && msg.recommendations.length > 0 && (
                    <CardCarousel
                      items={msg.recommendations}
                      onCardClick={onCardClick ?? setSelectedMovie}
                    />
                  )}
                  {msg.error && (
                    <MessageError
                      error={msg.error}
                      messageId={msg.id}
                      onRetry={onRetry}
                    />
                  )}
                </>
              ) : (
                <>
                  <p className="whitespace-pre-wrap break-words">
                    {msg.content}
                  </p>
                  {msg.error && (
                    <MessageError
                      error={msg.error}
                      messageId={msg.id}
                      onRetry={onRetry}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        ))}
      </div>
      <CardDetail
        item={selectedMovie}
        open={selectedMovie !== null}
        onClose={() => setSelectedMovie(null)}
      />
    </div>
  );
}
