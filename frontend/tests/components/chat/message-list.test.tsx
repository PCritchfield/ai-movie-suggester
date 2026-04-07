import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, toHaveNoViolations } from "jest-axe";
import type { ChatMessage } from "@/lib/api/types";
import { MessageList } from "@/components/chat/message-list";

expect.extend(toHaveNoViolations);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const userMessage: ChatMessage = {
  id: "u1",
  role: "user",
  content: "Something like Alien but funny",
};

const assistantMessage: ChatMessage = {
  id: "a1",
  role: "assistant",
  content: "Here are some **great** options:\n\n- Galaxy Quest\n- Spaceballs",
};

describe("MessageList", () => {
  it("renders user messages right-aligned and assistant messages left-aligned", () => {
    render(
      <MessageList
        messages={[userMessage, assistantMessage]}
        isStreaming={false}
      />
    );

    // User message content
    expect(
      screen.getByText("Something like Alien but funny")
    ).toBeInTheDocument();

    // Assistant message - check for markdown-rendered content
    expect(screen.getByText("Galaxy Quest")).toBeInTheDocument();

    // Check alignment via parent flex classes
    const messageElements = screen
      .getByRole("log")
      .querySelectorAll(":scope > div > div");
    // First message (user) should have justify-end
    expect(messageElements[0].className).toContain("justify-end");
    // Second message (assistant) should have justify-start
    expect(messageElements[1].className).toContain("justify-start");
  });

  it("renders markdown content (bold text renders as strong)", () => {
    render(<MessageList messages={[assistantMessage]} isStreaming={false} />);

    // remark-gfm + react-markdown should render **great** as <strong>
    const strong = screen.getByText("great");
    expect(strong.tagName).toBe("STRONG");
  });

  it("shows loading indicator when isStreaming and content is empty", () => {
    const streamingMsg: ChatMessage = {
      id: "a2",
      role: "assistant",
      content: "",
      isStreaming: true,
    };

    render(
      <MessageList messages={[userMessage, streamingMsg]} isStreaming={true} />
    );

    expect(screen.getByLabelText("Loading response")).toBeInTheDocument();
  });

  it("does not show loading indicator when content has arrived", () => {
    const streamingWithContent: ChatMessage = {
      id: "a3",
      role: "assistant",
      content: "Some content",
      isStreaming: true,
    };

    render(
      <MessageList
        messages={[userMessage, streamingWithContent]}
        isStreaming={true}
      />
    );

    expect(screen.queryByLabelText("Loading response")).not.toBeInTheDocument();
  });
});

// ─── Error Handling Tests ──────────────────────────────────────────────

describe("MessageList error handling", () => {
  it("SSE error event displays inline error message and retry button on assistant message", () => {
    const errorMsg: ChatMessage = {
      id: "a-err",
      role: "assistant",
      content: "",
      error: {
        code: "ollama_unavailable",
        message: "Ollama is not reachable",
      },
    };

    const onRetry = vi.fn();
    render(
      <MessageList
        messages={[userMessage, errorMsg]}
        isStreaming={false}
        onRetry={onRetry}
      />
    );

    expect(screen.getByText("Ollama is not reachable")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /retry message/i })
    ).toBeInTheDocument();
  });

  it("clicking retry calls onRetry with the message id", async () => {
    const user = userEvent.setup();
    const errorMsg: ChatMessage = {
      id: "a-err",
      role: "assistant",
      content: "",
      error: {
        code: "stream_interrupted",
        message: "Connection lost",
      },
    };

    const onRetry = vi.fn();
    render(
      <MessageList
        messages={[userMessage, errorMsg]}
        isStreaming={false}
        onRetry={onRetry}
      />
    );

    await user.click(screen.getByRole("button", { name: /retry message/i }));
    expect(onRetry).toHaveBeenCalledWith("a-err");
  });

  it("HTTP 401 error displays 'Log in again' link pointing to /login?reason=session_expired", () => {
    const errorMsg: ChatMessage = {
      id: "u-err",
      role: "user",
      content: "hello",
      error: {
        code: "generation_timeout",
        message: "Your session has expired.",
      },
    };

    render(
      <MessageList
        messages={[errorMsg]}
        isStreaming={false}
        onRetry={vi.fn()}
      />
    );

    const link = screen.getByText("Log in again");
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/login?reason=session_expired");
  });

  it("HTTP 429 error disables retry button with cooldown text and re-enables after timeout", async () => {
    vi.useFakeTimers();
    const errorMsg: ChatMessage = {
      id: "a-429",
      role: "assistant",
      content: "",
      error: {
        code: "generation_timeout",
        message: "Too many requests. Please wait a moment.",
      },
    };

    render(
      <MessageList
        messages={[userMessage, errorMsg]}
        isStreaming={false}
        onRetry={vi.fn()}
      />
    );

    const button = screen.getByRole("button", { name: /retry message/i });
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("Try again in a moment");

    // Advance past 10s cooldown
    act(() => {
      vi.advanceTimersByTime(10001);
    });

    expect(button).not.toBeDisabled();
    expect(button).toHaveTextContent("Retry");

    vi.useRealTimers();
  });

  it("error messages have role='alert' attribute", () => {
    const errorMsg: ChatMessage = {
      id: "a-alert",
      role: "assistant",
      content: "",
      error: {
        code: "search_unavailable",
        message: "Search is down",
      },
    };

    render(
      <MessageList
        messages={[errorMsg]}
        isStreaming={false}
        onRetry={vi.fn()}
      />
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Search is down")).toBeInTheDocument();
  });
});
