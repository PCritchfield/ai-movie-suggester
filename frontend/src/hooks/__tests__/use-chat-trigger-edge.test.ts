import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useChat } from "../use-chat";
import type { SSEEvent } from "@/lib/api/types";

// Mock the chat-stream module
vi.mock("@/lib/api/chat-stream", () => ({
  sendChatMessage: vi.fn(),
  parseSSEStream: vi.fn(),
}));

// Mock the client module (for clearHistory's apiDelete)
vi.mock("@/lib/api/client", () => ({
  apiDelete: vi.fn().mockResolvedValue(undefined),
}));

import { sendChatMessage, parseSSEStream } from "@/lib/api/chat-stream";
import { TRIGGERED_KEY } from "@/hooks/use-install-prompt";

/**
 * Helper: create a mock async generator from an array of SSE events.
 */
async function* mockSSEGenerator(events: SSEEvent[]): AsyncGenerator<SSEEvent> {
  for (const event of events) {
    yield event;
  }
}

/**
 * Helper: set up sendChatMessage + parseSSEStream mocks for a given event sequence.
 */
function mockStreamResponse(events: SSEEvent[]) {
  const fakeStream = {} as ReadableStream<Uint8Array>;
  vi.mocked(sendChatMessage).mockResolvedValue(fakeStream);
  vi.mocked(parseSSEStream).mockReturnValue(mockSSEGenerator(events));
}

describe("useChat — install banner trigger (edge cases)", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    // Mock crypto.randomUUID for stable message IDs
    vi.stubGlobal(
      "crypto",
      Object.assign({}, globalThis.crypto, {
        randomUUID: vi
          .fn()
          .mockReturnValueOnce("user-1")
          .mockReturnValueOnce("assistant-1")
          .mockReturnValueOnce("user-2")
          .mockReturnValueOnce("assistant-2"),
      })
    );
  });

  it("writes trigger flag when stream ends without a done event (fallback path)", async () => {
    // Stream yields text but terminates without a "done" event
    mockStreamResponse([
      { type: "text", content: "Here are some recommendations" },
    ]);

    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("recommend something");
    });
    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    expect(localStorage.getItem(TRIGGERED_KEY)).toBe("true");
  });

  it("does not crash when localStorage.setItem throws", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });

    mockStreamResponse([
      { type: "text", content: "Great movie!" },
      { type: "done" },
    ]);

    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("recommend something");
    });
    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    // setItem threw, so flag was NOT persisted — but the hook didn't crash.
    // Verify the hook still processed content correctly as proof it survived.
    const assistantMsg = result.current.messages.find(
      (m) => m.role === "assistant"
    );
    expect(assistantMsg?.content).toBe("Great movie!");

    vi.restoreAllMocks();
  });
});
