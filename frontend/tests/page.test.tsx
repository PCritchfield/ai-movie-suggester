import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// Mock useChat hook
vi.mock("@/hooks/use-chat", () => ({
  useChat: () => ({
    messages: [],
    isStreaming: false,
    error: null,
    sendMessage: vi.fn(),
    clearHistory: vi.fn(),
    retry: vi.fn(),
  }),
}));

// Mock react-markdown to avoid ESM issues in test
vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => children,
}));

import ChatPage from "@/app/(protected)/page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ChatPage", () => {
  it("renders message list and chat input", () => {
    render(<ChatPage />);
    // Message list has role="log"
    expect(screen.getByRole("log")).toBeInTheDocument();
    // Chat input has the textarea
    expect(screen.getByLabelText(/chat message/i)).toBeInTheDocument();
    // Send button
    expect(
      screen.getByRole("button", { name: /send message/i })
    ).toBeInTheDocument();
  });
});
