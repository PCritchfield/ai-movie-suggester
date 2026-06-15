import { describe, it, expect } from "vitest";
import { parseSSEStream } from "../chat-stream";
import type { SSEEvent } from "../types";

/** Build a ReadableStream<Uint8Array> from an SSE wire string. */
function streamFrom(text: string): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

async function collect(text: string): Promise<SSEEvent[]> {
  const out: SSEEvent[] = [];
  for await (const ev of parseSSEStream(streamFrom(text))) {
    out.push(ev);
  }
  return out;
}

describe("parseSSEStream — Spec 27 v2 events", () => {
  it("parses the full v2 success sequence", async () => {
    const wire = [
      `data: ${JSON.stringify({ type: "metadata", version: 2, recommendations: [], search_status: "ok", turn_count: 1 })}`,
      `data: ${JSON.stringify({ type: "status", phase: "generating" })}`,
      `data: ${JSON.stringify({ type: "picks", version: 2, picks: [{ jellyfin_id: "a1", reasoning: "scary", pick_order: 1 }] })}`,
      `data: ${JSON.stringify({ type: "text", content: "1. **Alien**" })}`,
      `data: ${JSON.stringify({ type: "done" })}`,
    ]
      .map((l) => `${l}\n\n`)
      .join("");

    const events = await collect(wire);
    expect(events.map((e) => e.type)).toEqual([
      "metadata",
      "status",
      "picks",
      "text",
      "done",
    ]);
  });

  it("parses a picks event payload", async () => {
    const events = await collect(
      `data: ${JSON.stringify({ type: "picks", version: 2, picks: [{ jellyfin_id: "g1", reasoning: "funny", pick_order: 2 }] })}\n\n`
    );
    expect(events).toHaveLength(1);
    const ev = events[0];
    expect(ev.type).toBe("picks");
    if (ev.type === "picks") {
      expect(ev.picks[0]).toEqual({
        jellyfin_id: "g1",
        reasoning: "funny",
        pick_order: 2,
      });
    }
  });

  it("silently skips malformed JSON frames", async () => {
    const wire =
      "data: not valid json {\n\n" +
      `data: ${JSON.stringify({ type: "done" })}\n\n`;
    const events = await collect(wire);
    expect(events.map((e) => e.type)).toEqual(["done"]);
  });
});
