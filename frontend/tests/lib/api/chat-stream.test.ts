import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { parseSSEStream, sendChatMessage } from "@/lib/api/chat-stream";
import { ApiAuthError, ApiError, NetworkError } from "@/lib/api/types";
import type { SSEEvent } from "@/lib/api/types";

// Mock getCsrfToken — preserve parseResponse for apiDelete tests
vi.mock("@/lib/api/shared", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/shared")>();
  return {
    ...actual,
    getCsrfToken: () => "test-csrf-token",
    getBaseUrl: () => "",
  };
});

/**
 * Helper: create a ReadableStream from an array of string chunks.
 * Each chunk simulates a network packet — may contain partial or multiple SSE frames.
 */
function createMockStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

// ─── parseSSEStream tests ───────────────────────────────────────────────

describe("parseSSEStream", () => {
  it("parses a single event", async () => {
    const stream = createMockStream([
      'data: {"type":"text","content":"hello"}\n\n',
    ]);
    const events: SSEEvent[] = [];
    for await (const event of parseSSEStream(stream)) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ type: "text", content: "hello" });
  });

  it("parses multiple events in one stream", async () => {
    const stream = createMockStream([
      'data: {"type":"metadata","version":1,"recommendations":[],"search_status":"ok","turn_count":1}\n\n' +
        'data: {"type":"text","content":"token1"}\n\n' +
        'data: {"type":"text","content":"token2"}\n\n' +
        'data: {"type":"done"}\n\n',
    ]);
    const events: SSEEvent[] = [];
    for await (const event of parseSSEStream(stream)) {
      events.push(event);
    }
    expect(events).toHaveLength(4);
    expect(events[0].type).toBe("metadata");
    expect(events[1]).toEqual({ type: "text", content: "token1" });
    expect(events[2]).toEqual({ type: "text", content: "token2" });
    expect(events[3]).toEqual({ type: "done" });
  });

  it("handles chunks split across SSE frame boundaries", async () => {
    // Split a single event across multiple chunks
    const stream = createMockStream([
      'data: {"type":"te',
      'xt","content":"hello"}\n',
      "\n",
    ]);
    const events: SSEEvent[] = [];
    for await (const event of parseSSEStream(stream)) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ type: "text", content: "hello" });
  });

  it("handles malformed JSON gracefully (skips without throwing)", async () => {
    const stream = createMockStream([
      "data: {not valid json}\n\n" +
        'data: {"type":"text","content":"valid"}\n\n',
    ]);
    const events: SSEEvent[] = [];
    for await (const event of parseSSEStream(stream)) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ type: "text", content: "valid" });
  });

  it("yields nothing for an empty stream", async () => {
    const stream = createMockStream([]);
    const events: SSEEvent[] = [];
    for await (const event of parseSSEStream(stream)) {
      events.push(event);
    }
    expect(events).toHaveLength(0);
  });

  it("parses error events with correct code and message", async () => {
    const stream = createMockStream([
      'data: {"type":"error","code":"ollama_unavailable","message":"Ollama is not reachable"}\n\n',
    ]);
    const events: SSEEvent[] = [];
    for await (const event of parseSSEStream(stream)) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      type: "error",
      code: "ollama_unavailable",
      message: "Ollama is not reachable",
    });
  });

  it("handles events split across many small chunks", async () => {
    // Simulate byte-at-a-time delivery
    const fullMessage = 'data: {"type":"done"}\n\n';
    const chunks = fullMessage.split("").map((c) => c);
    const stream = createMockStream(chunks);
    const events: SSEEvent[] = [];
    for await (const event of parseSSEStream(stream)) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ type: "done" });
  });
});

// ─── sendChatMessage tests ──────────────────────────────────────────────

describe("sendChatMessage", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("includes CSRF token and credentials in request", async () => {
    const mockBody = createMockStream([]);
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: mockBody,
    });
    globalThis.fetch = mockFetch;

    await sendChatMessage("hello");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/chat",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: expect.objectContaining({
          "X-CSRF-Token": "test-csrf-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ message: "hello" }),
      })
    );
  });

  it("returns response.body stream on success", async () => {
    const mockBody = createMockStream([]);
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: mockBody,
    });

    const result = await sendChatMessage("hello");
    expect(result).toBe(mockBody);
  });

  it("throws ApiAuthError on 401", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "Unauthorized" }),
    });

    await expect(sendChatMessage("hello")).rejects.toThrow(ApiAuthError);
  });

  it("throws ApiAuthError on 403", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: "Forbidden" }),
    });

    await expect(sendChatMessage("hello")).rejects.toThrow(ApiAuthError);
  });

  it("throws ApiError on 429", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      json: () => Promise.resolve({ detail: "Rate limited" }),
    });

    await expect(sendChatMessage("hello")).rejects.toThrow(ApiError);
    try {
      await sendChatMessage("hello");
    } catch (err) {
      expect((err as ApiError).status).toBe(429);
    }
  });

  it("throws ApiError on 422", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: "Validation error" }),
    });

    await expect(sendChatMessage("hello")).rejects.toThrow(ApiError);
    try {
      await sendChatMessage("hello");
    } catch (err) {
      expect((err as ApiError).status).toBe(422);
    }
  });

  it("throws NetworkError on fetch TypeError", async () => {
    globalThis.fetch = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(sendChatMessage("hello")).rejects.toThrow(NetworkError);
  });
});

// ─── apiDelete tests ────────────────────────────────────────────────────

describe("apiDelete", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  // We need to import apiDelete — it uses networkFetch from client.ts
  // which wraps global fetch. Let's test it via the module.

  it("sends DELETE method with CSRF token", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    });
    globalThis.fetch = mockFetch;

    const { apiDelete } = await import("@/lib/api/client");
    await apiDelete("/api/chat/history");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/chat/history",
      expect.objectContaining({
        method: "DELETE",
        credentials: "include",
        headers: expect.objectContaining({
          "X-CSRF-Token": "test-csrf-token",
        }),
      })
    );
  });

  it("returns void on 204", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    });

    const { apiDelete } = await import("@/lib/api/client");
    const result = await apiDelete("/api/chat/history");
    expect(result).toBeUndefined();
  });

  it("throws ApiAuthError on 401", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "Unauthorized" }),
    });

    const { apiDelete } = await import("@/lib/api/client");
    await expect(apiDelete("/api/chat/history")).rejects.toThrow(ApiAuthError);
  });

  it("throws ApiError on 500", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: "Internal error" }),
    });

    const { apiDelete } = await import("@/lib/api/client");
    await expect(apiDelete("/api/chat/history")).rejects.toThrow(ApiError);
  });
});
