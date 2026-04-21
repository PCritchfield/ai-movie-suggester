import { ApiAuthError, ApiError } from "./types";

export function getBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.BACKEND_URL || "http://localhost:8000";
  }
  return "";
}

/**
 * Backend URL for client-side streaming (SSE) requests.
 *
 * Next.js rewrites buffer the entire response before returning it,
 * which breaks SSE streaming. For endpoints that stream (e.g. /api/chat),
 * the client must fetch directly from the backend, bypassing the rewrite.
 *
 * Falls back to same-origin rewrite ("") if not configured — streaming
 * will be buffered but still functional (just not incremental).
 */
export function getStreamBaseUrl(): string {
  // Server-side: use the internal backend URL (same as getBaseUrl)
  if (typeof window === "undefined") {
    return getBaseUrl();
  }
  // Client-side: use the public backend URL for direct SSE streaming,
  // or fall back to same-origin rewrite ("") if not configured
  return process.env.NEXT_PUBLIC_BACKEND_URL || "";
}

export async function parseResponse<T>(response: Response): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.status === 401 || response.status === 403) {
    throw new ApiAuthError(response.status, body);
  }

  if (!response.ok) {
    throw new ApiError(response.status, body);
  }

  return body as T;
}

export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrf_token="));
  return match ? match.split("=")[1] : null;
}
