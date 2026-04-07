"use client";

import { useChat } from "@/hooks/use-chat";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";

export default function ChatPage() {
  const { messages, isStreaming, sendMessage, retry } = useChat();

  return (
    <div className="flex flex-col" style={{ height: "100dvh" }}>
      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        onRetry={retry}
      />
      <ChatInput onSend={sendMessage} isStreaming={isStreaming} />
    </div>
  );
}
