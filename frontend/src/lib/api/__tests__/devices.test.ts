import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiAuthError } from "../types";
import type { Device } from "../types";

function mockFetch(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    })
  );
}

describe("fetchDevices", () => {
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

  it("returns the Device[] payload on 200", async () => {
    const canonicalPayload: Device[] = [
      {
        session_id: "a1b2c3d4",
        name: "Living Room TV",
        client: "Jellyfin Android TV",
        device_type: "Tv",
      },
      {
        session_id: "e5f6g7h8",
        name: "Kitchen iPad",
        client: "Jellyfin iOS",
        device_type: "Tablet",
      },
    ];
    mockFetch(200, canonicalPayload);

    const { fetchDevices } = await import("../devices");
    const result = await fetchDevices();

    expect(result).toEqual(canonicalPayload);
    expect(result).toHaveLength(2);
    expect(result[0].device_type).toBe("Tv");
  });

  it("calls GET /api/devices with credentials: include", async () => {
    mockFetch(200, []);
    const { fetchDevices } = await import("../devices");
    await fetchDevices();

    expect(fetch).toHaveBeenCalledWith(
      "/api/devices",
      expect.objectContaining({
        method: "GET",
        credentials: "include",
      })
    );
  });

  it("returns an empty array on 200 with empty list", async () => {
    mockFetch(200, []);
    const { fetchDevices } = await import("../devices");
    const result = await fetchDevices();

    expect(result).toEqual([]);
    expect(result).toHaveLength(0);
  });

  it("rejects with ApiAuthError on 401", async () => {
    mockFetch(401, { detail: "Not authenticated" });
    const { fetchDevices } = await import("../devices");

    await expect(fetchDevices()).rejects.toThrow(ApiAuthError);
    await expect(fetchDevices()).rejects.toHaveProperty("status", 401);
  });

  it("rejects with ApiAuthError on 403", async () => {
    // parseResponse throws ApiAuthError on both 401 and 403 (see shared.ts).
    // Asserting 403 defends against a future shared.ts change that would
    // narrow this to 401 only and silently downgrade 403s to generic errors.
    mockFetch(403, { detail: "Forbidden" });
    const { fetchDevices } = await import("../devices");

    await expect(fetchDevices()).rejects.toThrow(ApiAuthError);
    await expect(fetchDevices()).rejects.toHaveProperty("status", 403);
  });
});
