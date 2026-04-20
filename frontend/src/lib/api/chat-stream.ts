import { getCsrfToken, getStreamBaseUrl, parseResponse } from "./shared";
import { networkFetch } from "./client";
import type { SSEEvent } from "./types";

/**
 * Async generator that parses an SSE stream from POST /api/chat.
 *
 * SSE framing: each event is `data: {json}\n\n`. No `event:` or `id:` fields.
 * Handles partial chunks that split across frame boundaries via a carry buffer.
 * Malformed JSON lines are silently skipped (not thrown).
 */
export async function* parseSSEStream(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<SSEEvent> {
  const decoder = new TextDecoderStream();
  const reader = (stream as ReadableStream).pipeThrough(decoder).getReader();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += value;

      // Split on double newlines (SSE frame boundary)
      const frames = buffer.split("\n\n");
      // Last element may be incomplete — keep it in the buffer
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const trimmed = frame.trim();
        if (!trimmed) continue;

        // Strip `data: ` prefix
        const dataLine = trimmed
          .split("\n")
          .find((line) => line.startsWith("data: "));
        if (!dataLine) continue;

        const jsonStr = dataLine.slice("data: ".length);
        try {
          const event = JSON.parse(jsonStr) as SSEEvent;
          yield event;
        } catch {
          // Malformed JSON — skip silently
        }
      }
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // cancel() may reject if stream already closed — safe to ignore
    }
    reader.releaseLock();
  }
}

/**
 * Send a chat message and return the SSE response stream.
 *
 * POST /api/chat with JSON body { message }, CSRF token, and credentials.
 * On success, returns the ReadableStream for consumption by parseSSEStream().
 * On error, throws ApiAuthError (401/403), ApiError (429/422), or NetworkError.
 *
 * Reuses networkFetch (NetworkError wrapping) and parseResponse (error
 * classification) from the shared API client. The only difference from
 * apiPost is that on success we return the raw stream, not parsed JSON.
 */
export async function sendChatMessage(
  message: string
): Promise<ReadableStream<Uint8Array>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const csrf = getCsrfToken();
  if (csrf) {
    headers["X-CSRF-Token"] = csrf;
  }

  const response = await networkFetch(`${getStreamBaseUrl()}/api/chat`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify({ message }),
  });

  // For non-OK responses, delegate to parseResponse which throws
  // ApiAuthError (401/403) or ApiError (other statuses)
  if (!response.ok) {
    await parseResponse<never>(response);
  }

  if (!response.body) {
    throw new Error("Response body is null — expected SSE stream");
  }

  return response.body;
}
