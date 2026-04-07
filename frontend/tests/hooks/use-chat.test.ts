import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { SSEEvent } from "@/lib/api/types";

// Mock sendChatMessage and parseSSEStream
const mockSendChatMessage = vi.fn();
const mockParseSSEStream = vi.fn();

vi.mock("@/lib/api/chat-stream", () => ({
  sendChatMessage: (...args: unknown[]) => mockSendChatMessage(...args),
  parseSSEStream: (...args: unknown[]) => mockParseSSEStream(...args),
}));

// Mock apiDelete
const mockApiDelete = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiDelete: (...args: unknown[]) => mockApiDelete(...args),
}));

// Mock crypto.randomUUID
let uuidCounter = 0;
vi.stubGlobal("crypto", {
  randomUUID: () => `uuid-${++uuidCounter}`,
});

import { useChat } from "@/hooks/use-chat";

/**
 * Helper: create an async generator from an array of SSE events.
 */
async function* mockSSEGenerator(events: SSEEvent[]): AsyncGenerator<SSEEvent> {
  for (const event of events) {
    yield event;
  }
}

describe("useChat", () => {
  beforeEach(() => {
    uuidCounter = 0;
    mockSendChatMessage.mockReset();
    mockParseSSEStream.mockReset();
    mockApiDelete.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sendMessage appends user message + placeholder assistant message", async () => {
    const mockStream = {};
    mockSendChatMessage.mockResolvedValue(mockStream);
    mockParseSSEStream.mockReturnValue(
      mockSSEGenerator([{ type: "done" as const }])
    );

    const { result } = renderHook(() => useChat());

    expect(result.current.messages).toHaveLength(0);

    act(() => {
      result.current.sendMessage("hello");
    });

    // Messages should be added synchronously
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.messages[0].content).toBe("hello");
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.messages[1].isStreaming).toBe(true);
  });

  it("TEXT events accumulate content in assistant message", async () => {
    const mockStream = {};
    mockSendChatMessage.mockResolvedValue(mockStream);
    mockParseSSEStream.mockReturnValue(
      mockSSEGenerator([
        { type: "text" as const, content: "Hello " },
        { type: "text" as const, content: "world!" },
        { type: "done" as const },
      ])
    );

    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("hi");
    });

    await waitFor(
      () => {
        expect(result.current.isStreaming).toBe(false);
      },
      { timeout: 3000 }
    );

    const assistant = result.current.messages.find(
      (m) => m.role === "assistant"
    );
    expect(assistant?.content).toBe("Hello world!");
  });

  it("DONE event clears isStreaming and flushes remaining text", async () => {
    const mockStream = {};
    mockSendChatMessage.mockResolvedValue(mockStream);
    mockParseSSEStream.mockReturnValue(
      mockSSEGenerator([
        { type: "text" as const, content: "final text" },
        { type: "done" as const },
      ])
    );

    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test");
    });

    await waitFor(
      () => {
        expect(result.current.isStreaming).toBe(false);
      },
      { timeout: 3000 }
    );

    const assistant = result.current.messages.find(
      (m) => m.role === "assistant"
    );
    expect(assistant?.content).toBe("final text");
    expect(assistant?.isStreaming).toBe(false);
  });

  it("ERROR event sets error field on assistant message", async () => {
    const mockStream = {};
    mockSendChatMessage.mockResolvedValue(mockStream);
    mockParseSSEStream.mockReturnValue(
      mockSSEGenerator([
        {
          type: "error" as const,
          code: "ollama_unavailable" as const,
          message: "Ollama is down",
        },
      ])
    );

    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("test");
    });

    await waitFor(
      () => {
        expect(result.current.isStreaming).toBe(false);
      },
      { timeout: 3000 }
    );

    const assistant = result.current.messages.find(
      (m) => m.role === "assistant"
    );
    expect(assistant?.error).toEqual({
      code: "ollama_unavailable",
      message: "Ollama is down",
    });
  });

  it("prevents concurrent sends (second sendMessage is no-op while streaming)", () => {
    // Make sendChatMessage hang forever (never resolves)
    mockSendChatMessage.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("first");
    });

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages).toHaveLength(2);

    act(() => {
      result.current.sendMessage("second");
    });

    // Should still only have 2 messages (1 user + 1 assistant from "first")
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].content).toBe("first");
  });

  it("clearHistory calls apiDelete and resets messages to empty", async () => {
    mockApiDelete.mockResolvedValue(undefined);
    const mockStream = {};
    mockSendChatMessage.mockResolvedValue(mockStream);
    mockParseSSEStream.mockReturnValue(
      mockSSEGenerator([
        { type: "text" as const, content: "response" },
        { type: "done" as const },
      ])
    );

    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("hello");
    });

    await waitFor(
      () => {
        expect(result.current.isStreaming).toBe(false);
      },
      { timeout: 3000 }
    );

    expect(result.current.messages.length).toBeGreaterThan(0);

    await act(async () => {
      await result.current.clearHistory();
    });

    expect(mockApiDelete).toHaveBeenCalledWith("/api/chat/history");
    expect(result.current.messages).toHaveLength(0);
  });
});
