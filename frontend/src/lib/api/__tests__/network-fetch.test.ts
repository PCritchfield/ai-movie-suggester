import { describe, it, expect, vi, beforeEach } from "vitest";
import { networkFetch } from "../client";
import { NetworkError } from "../types";

describe("networkFetch", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns response on successful fetch", async () => {
    const mockResponse = new Response("ok", { status: 200 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const result = await networkFetch("http://example.com", {});
    expect(result.status).toBe(200);
  });

  it("wraps TypeError into NetworkError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
    );

    await expect(networkFetch("http://example.com", {})).rejects.toThrow(
      NetworkError
    );
    await expect(networkFetch("http://example.com", {})).rejects.toThrow(
      "Server unreachable"
    );
  });

  it("re-throws non-TypeError errors", async () => {
    const error = new Error("Some other error");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));

    await expect(networkFetch("http://example.com", {})).rejects.toThrow(
      "Some other error"
    );
    await expect(
      networkFetch("http://example.com", {})
    ).rejects.not.toBeInstanceOf(NetworkError);
  });
});
