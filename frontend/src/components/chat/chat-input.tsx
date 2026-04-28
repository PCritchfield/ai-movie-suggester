"use client";

import {
  useRef,
  useState,
  useCallback,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Send } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string) => void;
  isStreaming: boolean;
}

export function ChatInput({ onSend, isStreaming }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [hasContent, setHasContent] = useState(false);

  const resetTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.value = "";
      textarea.style.height = "auto";
      textarea.focus();
      setHasContent(false);
    }
  }, []);

  const doSend = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const text = textarea.value.trim();
    if (!text || isStreaming) return;
    onSend(text);
    resetTextarea();
  }, [isStreaming, onSend, resetTextarea]);

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      doSend();
    },
    [doSend]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        doSend();
      }
    },
    [doSend]
  );

  const handleInput = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    // Track whether the textarea has non-whitespace content
    setHasContent(textarea.value.trim().length > 0);
    // Reset height to auto to get the correct scrollHeight
    textarea.style.height = "auto";
    // Max height: approximately 6 lines (~144px)
    const maxHeight = 144;
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
    // Enable scrolling when content exceeds max height
    textarea.style.overflowY =
      textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, []);

  return (
    <div
      className="sticky bottom-0 border-t bg-background"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <form
        onSubmit={handleSubmit}
        className="mx-auto flex max-w-3xl items-end gap-2 px-4 py-3"
      >
        <textarea
          ref={textareaRef}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder="Ask for movie recommendations..."
          maxLength={1000}
          rows={1}
          disabled={isStreaming}
          aria-label="Chat message"
          className="flex-1 resize-none rounded-xl border bg-muted px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          style={{ overflow: "hidden" }}
        />
        <button
          type="submit"
          disabled={isStreaming || !hasContent}
          aria-label="Send message"
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Send className="h-5 w-5" aria-hidden="true" />
        </button>
      </form>
    </div>
  );
}
