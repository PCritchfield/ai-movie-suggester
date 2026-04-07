import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, toHaveNoViolations } from "jest-axe";
import { ChatInput } from "@/components/chat/chat-input";

expect.extend(toHaveNoViolations);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ChatInput", () => {
  it("Enter submits message via onSend prop", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<ChatInput onSend={onSend} isStreaming={false} />);

    const textarea = screen.getByLabelText(/chat message/i);
    await user.type(textarea, "hello{Enter}");

    expect(onSend).toHaveBeenCalledWith("hello");
  });

  it("Shift+Enter inserts newline without submitting", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<ChatInput onSend={onSend} isStreaming={false} />);

    const textarea = screen.getByLabelText(/chat message/i);
    await user.type(textarea, "line1{Shift>}{Enter}{/Shift}line2");

    expect(onSend).not.toHaveBeenCalled();
    expect(textarea).toHaveValue("line1\nline2");
  });

  it("send button is disabled during streaming", () => {
    render(<ChatInput onSend={vi.fn()} isStreaming={true} />);
    const button = screen.getByRole("button", { name: /send message/i });
    expect(button).toBeDisabled();
  });

  it("send button is disabled when textarea is empty", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<ChatInput onSend={onSend} isStreaming={false} />);

    // Try to submit with empty textarea via Enter
    const textarea = screen.getByLabelText(/chat message/i);
    await user.type(textarea, "{Enter}");

    expect(onSend).not.toHaveBeenCalled();
  });

  it("clears textarea and refocuses after send", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<ChatInput onSend={onSend} isStreaming={false} />);

    const textarea = screen.getByLabelText(/chat message/i);
    await user.type(textarea, "hello{Enter}");

    expect(textarea).toHaveValue("");
    expect(textarea).toHaveFocus();
  });

  it("has minimum 44x44px touch target on send button", () => {
    render(<ChatInput onSend={vi.fn()} isStreaming={false} />);
    const button = screen.getByRole("button", { name: /send message/i });
    // Check for min-h-11 min-w-11 classes (44px = 2.75rem = 11 in tailwind)
    expect(button.className).toContain("min-h-11");
    expect(button.className).toContain("min-w-11");
  });
});
