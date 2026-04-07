import { getCsrfToken, getBaseUrl } from "./shared";
import { ApiAuthError, ApiError, NetworkError } from "./types";
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
    reader.releaseLock();
  }
}

/**
 * Send a chat message and return the SSE response stream.
 *
 * POST /api/chat with JSON body { message }, CSRF token, and credentials.
 * On success, returns the ReadableStream for consumption by parseSSEStream().
 * On error, throws ApiAuthError (401/403), ApiError (429/422), or NetworkError.
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

  let response: Response;
  try {
    response = await fetch(`${getBaseUrl()}/api/chat`, {
      method: "POST",
      credentials: "include",
      headers,
      body: JSON.stringify({ message }),
    });
  } catch (err) {
    if (err instanceof TypeError) {
      throw new NetworkError();
    }
    throw err;
  }

  if (response.status === 401 || response.status === 403) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw new ApiAuthError(response.status as 401 | 403, body);
  }

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw new ApiError(response.status, body);
  }

  if (!response.body) {
    throw new Error("Response body is null — expected SSE stream");
  }

  return response.body;
}
