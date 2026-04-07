import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
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
