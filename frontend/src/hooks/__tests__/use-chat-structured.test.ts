import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useChat } from "../use-chat";
import type { SSEEvent } from "@/lib/api/types";

vi.mock("@/lib/api/chat-stream", () => ({
  sendChatMessage: vi.fn(),
  parseSSEStream: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({
  apiDelete: vi.fn().mockResolvedValue(undefined),
}));

import { sendChatMessage, parseSSEStream } from "@/lib/api/chat-stream";

async function* gen(events: SSEEvent[]): AsyncGenerator<SSEEvent> {
  for (const e of events) yield e;
}

function mockStream(events: SSEEvent[]) {
  vi.mocked(sendChatMessage).mockResolvedValue(
    {} as ReadableStream<Uint8Array>
  );
  vi.mocked(parseSSEStream).mockReturnValue(gen(events));
}

const META = (recs: { jellyfin_id: string; title: string }[]): SSEEvent => ({
  type: "metadata",
  version: 2,
  recommendations: recs.map((r) => ({
    jellyfin_id: r.jellyfin_id,
    title: r.title,
    overview: null,
    genres: [],
    year: null,
    score: 0.8,
    poster_url: `/p/${r.jellyfin_id}`,
    community_rating: null,
    runtime_minutes: null,
    jellyfin_web_url: null,
  })),
  search_status: "ok",
  turn_count: 1,
});

describe("useChat — Spec 27 structured output", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    vi.stubGlobal(
      "crypto",
      Object.assign({}, globalThis.crypto, {
        randomUUID: vi
          .fn()
          .mockReturnValueOnce("user-1")
          .mockReturnValueOnce("assistant-1"),
      })
    );
  });

  it("stores picks and clears status on the assistant message", async () => {
    mockStream([
      META([
        { jellyfin_id: "a1", title: "Alien" },
        { jellyfin_id: "g1", title: "Galaxy Quest" },
      ]),
      { type: "status", phase: "generating" },
      {
        type: "picks",
        version: 2,
        picks: [{ jellyfin_id: "g1", reasoning: "funny", pick_order: 1 }],
      },
      { type: "text", content: "1. **Galaxy Quest** — funny" },
      { type: "done" },
    ]);

    const { result } = renderHook(() => useChat());
    act(() => result.current.sendMessage("like alien but funny"));

    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    const assistant = result.current.messages.find(
      (m) => m.role === "assistant"
    );
    expect(assistant?.picks).toEqual([
      { jellyfin_id: "g1", reasoning: "funny", pick_order: 1 },
    ]);
    expect(assistant?.statusPhase).toBeUndefined();
    expect(assistant?.recommendations).toHaveLength(2);
    expect(assistant?.content).toContain("Galaxy Quest");
  });

  it("ignores unknown event types without crashing (backward-compat)", async () => {
    mockStream([
      META([{ jellyfin_id: "a1", title: "Alien" }]),
      // An event type this client version doesn't know about.
      { type: "future_event", surprise: true } as unknown as SSEEvent,
      { type: "text", content: "hi" },
      { type: "done" },
    ]);

    const { result } = renderHook(() => useChat());
    act(() => result.current.sendMessage("hello"));

    await waitFor(() => expect(result.current.isStreaming).toBe(false));
    const assistant = result.current.messages.find(
      (m) => m.role === "assistant"
    );
    expect(assistant?.content).toBe("hi");
    expect(assistant?.error).toBeUndefined();
  });

  it("leaves picks undefined when no picks event arrives (v1 / fallback)", async () => {
    mockStream([
      META([{ jellyfin_id: "a1", title: "Alien" }]),
      { type: "status", phase: "generating" },
      { type: "text", content: "couldn't put together a recommendation" },
      { type: "done" },
    ]);

    const { result } = renderHook(() => useChat());
    act(() => result.current.sendMessage("hi"));

    await waitFor(() => expect(result.current.isStreaming).toBe(false));
    const assistant = result.current.messages.find(
      (m) => m.role === "assistant"
    );
    expect(assistant?.picks).toBeUndefined();
    expect(assistant?.recommendations).toHaveLength(1);
  });
});
