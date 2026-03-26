import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiAuthError, ApiError } from "../types";

function mockFetch(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    }),
  );
}

describe("apiGet", () => {
  beforeEach(() => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "csrf_token=test-csrf-value",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie = "";
  });

  it("sends credentials: include", async () => {
    mockFetch(200, { ok: true });
    const { apiGet } = await import("../client");
    await apiGet("/api/auth/me");
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("does NOT set X-CSRF-Token header", async () => {
    mockFetch(200, { ok: true });
    const { apiGet } = await import("../client");
    await apiGet("/api/auth/me");
    const call = vi.mocked(fetch).mock.calls[0];
    const headers = call[1]?.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("returns parsed JSON on 200", async () => {
    mockFetch(200, { user_id: "u1", username: "alice" });
    const { apiGet } = await import("../client");
    const result = await apiGet<{ user_id: string }>("/api/auth/me");
    expect(result.user_id).toBe("u1");
  });

  it("throws ApiAuthError on 401", async () => {
    mockFetch(401, { detail: "Not authenticated" });
    const { apiGet } = await import("../client");
    await expect(apiGet("/api/auth/me")).rejects.toThrow(ApiAuthError);
    await expect(apiGet("/api/auth/me")).rejects.toHaveProperty(
      "status",
      401,
    );
  });

  it("throws ApiError on 500", async () => {
    mockFetch(500, { detail: "Server error" });
    const { apiGet } = await import("../client");
    await expect(apiGet("/api/auth/me")).rejects.toThrow(ApiError);
    await expect(apiGet("/api/auth/me")).rejects.toHaveProperty(
      "status",
      500,
    );
  });
});

describe("apiPost", () => {
  beforeEach(() => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "csrf_token=test-csrf-value",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie = "";
  });

  it("sends credentials: include", async () => {
    mockFetch(200, { ok: true });
    const { apiPost } = await import("../client");
    await apiPost("/api/auth/login", { username: "alice" });
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("reads CSRF cookie and sets X-CSRF-Token header", async () => {
    mockFetch(200, { ok: true });
    const { apiPost } = await import("../client");
    await apiPost("/api/auth/login", { username: "alice" });
    const call = vi.mocked(fetch).mock.calls[0];
    const headers = call[1]?.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("test-csrf-value");
  });

  it("returns parsed JSON on 200", async () => {
    mockFetch(200, { user_id: "u1", username: "alice" });
    const { apiPost } = await import("../client");
    const result = await apiPost<{ user_id: string }>(
      "/api/auth/login",
      { username: "alice" },
    );
    expect(result.user_id).toBe("u1");
  });

  it("throws ApiAuthError on 403", async () => {
    mockFetch(403, { detail: "Forbidden" });
    const { apiPost } = await import("../client");
    await expect(
      apiPost("/api/auth/login", { username: "alice" }),
    ).rejects.toThrow(ApiAuthError);
    await expect(
      apiPost("/api/auth/login", { username: "alice" }),
    ).rejects.toHaveProperty("status", 403);
  });

  it("throws ApiError on 502", async () => {
    mockFetch(502, { detail: "Bad gateway" });
    const { apiPost } = await import("../client");
    await expect(
      apiPost("/api/auth/login", { username: "alice" }),
    ).rejects.toThrow(ApiError);
    await expect(
      apiPost("/api/auth/login", { username: "alice" }),
    ).rejects.toHaveProperty("status", 502);
  });
});
