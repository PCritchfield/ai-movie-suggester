import { describe, it, expect, vi, afterEach } from "vitest";

// Mock next/headers before any imports that use it
vi.mock("next/headers", () => ({
  cookies: vi.fn(),
}));

describe("buildCookieHeader", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns session_id=<value> when cookie exists", async () => {
    const { buildCookieHeader } = await import("../server");
    const mockReader = {
      get: (name: string) =>
        name === "session_id" ? { value: "abc123" } : undefined,
    };
    expect(buildCookieHeader(mockReader)).toBe("session_id=abc123");
  });

  it("returns empty string when no session cookie", async () => {
    const { buildCookieHeader } = await import("../server");
    const mockReader = {
      get: () => undefined,
    };
    expect(buildCookieHeader(mockReader)).toBe("");
  });
});

describe("serverGet", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls fetch with forwarded cookie header", async () => {
    const mockCookies = vi.fn().mockReturnValue({
      get: (name: string) =>
        name === "session_id" ? { value: "sess-xyz" } : undefined,
    });
    const { cookies } = await import("next/headers");
    vi.mocked(cookies).mockImplementation(mockCookies);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ user_id: "u1" }),
      })
    );

    const { serverGet } = await import("../server");
    await serverGet("/api/auth/me");

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/auth/me"),
      expect.objectContaining({
        headers: expect.objectContaining({
          Cookie: "session_id=sess-xyz",
        }),
      })
    );
  });
});
