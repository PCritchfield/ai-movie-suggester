import { renderHook, act } from "@testing-library/react";
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

const TRIGGERED_KEY = "pwa-chat-triggered";

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

describe("useChat — install banner trigger", () => {
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

  it("writes trigger flag to localStorage on first successful stream", async () => {
    mockStreamResponse([
      { type: "text", content: "Great movie!" },
      { type: "done" },
    ]);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      result.current.sendMessage("recommend something");
      // Allow microtasks to flush (stream processing)
      await vi.waitFor(() => {
        expect(result.current.isStreaming).toBe(false);
      });
    });

    expect(localStorage.getItem(TRIGGERED_KEY)).toBe("true");
  });

  it("dispatches pwa-trigger DOM event on first successful stream", async () => {
    mockStreamResponse([
      { type: "text", content: "Great movie!" },
      { type: "done" },
    ]);

    const listener = vi.fn();
    window.addEventListener("pwa-trigger", listener);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      result.current.sendMessage("recommend something");
      await vi.waitFor(() => {
        expect(result.current.isStreaming).toBe(false);
      });
    });

    expect(listener).toHaveBeenCalledOnce();

    window.removeEventListener("pwa-trigger", listener);
  });

  it("does NOT write flag again on subsequent successful streams", async () => {
    // First stream
    mockStreamResponse([
      { type: "text", content: "Great movie!" },
      { type: "done" },
    ]);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      result.current.sendMessage("first message");
      await vi.waitFor(() => {
        expect(result.current.isStreaming).toBe(false);
      });
    });

    expect(localStorage.getItem(TRIGGERED_KEY)).toBe("true");

    // Spy on setItem AFTER the first write
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");

    // Second stream
    mockStreamResponse([
      { type: "text", content: "Another recommendation!" },
      { type: "done" },
    ]);

    await act(async () => {
      result.current.sendMessage("second message");
      await vi.waitFor(() => {
        expect(result.current.isStreaming).toBe(false);
      });
    });

    // setItem should NOT have been called with the trigger key
    const triggerCalls = setItemSpy.mock.calls.filter(
      ([key]) => key === TRIGGERED_KEY
    );
    expect(triggerCalls).toHaveLength(0);

    setItemSpy.mockRestore();
  });

  it("does NOT write flag when stream ends with an error event", async () => {
    mockStreamResponse([
      { type: "text", content: "partial..." },
      {
        type: "error",
        code: "ollama_unavailable",
        message: "Ollama is down",
      },
    ]);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      result.current.sendMessage("recommend something");
      await vi.waitFor(() => {
        expect(result.current.isStreaming).toBe(false);
      });
    });

    expect(localStorage.getItem(TRIGGERED_KEY)).toBeNull();
  });

  it("does NOT write flag when stream completes with empty content", async () => {
    mockStreamResponse([{ type: "done" }]);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      result.current.sendMessage("recommend something");
      await vi.waitFor(() => {
        expect(result.current.isStreaming).toBe(false);
      });
    });

    expect(localStorage.getItem(TRIGGERED_KEY)).toBeNull();
  });
});
