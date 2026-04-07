import { getCsrfToken, getBaseUrl, parseResponse } from "./shared";
import { NetworkError } from "./types";

async function networkFetch(
  input: string,
  init: RequestInit
): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (err) {
    if (err instanceof TypeError) {
      throw new NetworkError();
    }
    throw err;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await networkFetch(`${getBaseUrl()}${path}`, {
    method: "GET",
    credentials: "include",
  });
  return parseResponse<T>(response);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const csrf = getCsrfToken();
  if (csrf) {
    headers["X-CSRF-Token"] = csrf;
  }

  const response = await networkFetch(`${getBaseUrl()}${path}`, {
    method: "POST",
    credentials: "include",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return parseResponse<T>(response);
}

export async function apiDelete(path: string): Promise<void> {
  const headers: Record<string, string> = {};

  const csrf = getCsrfToken();
  if (csrf) {
    headers["X-CSRF-Token"] = csrf;
  }

  const response = await networkFetch(`${getBaseUrl()}${path}`, {
    method: "DELETE",
    credentials: "include",
    headers,
  });

  if (response.status === 204) {
    return;
  }

  // For non-204 responses, use parseResponse to handle errors consistently
  await parseResponse<void>(response);
}
