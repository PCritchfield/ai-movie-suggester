import { ApiAuthError, ApiError } from "./types";

export function getBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.BACKEND_URL || "http://localhost:8000";
  }
  return "";
}

export async function parseResponse<T>(response: Response): Promise<T> {
  const body: unknown = await response.json();

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
