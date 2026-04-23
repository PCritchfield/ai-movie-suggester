import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  ApiAuthError,
  DeviceOfflineError,
  PlaybackFailedError,
} from "../types";
import type { Device, PlayRequest } from "../types";
import * as client from "../client";

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

describe("postPlay", () => {
  const validRequest: PlayRequest = {
    item_id: "f4e3d2c1",
    session_id: "a1b2c3d4",
  };

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

  it("resolves to PlayResponse {status, device_name} on 200 and routes through apiPost (not raw fetch)", async () => {
    mockFetch(200, { status: "ok", device_name: "Living Room TV" });
    const apiPostSpy = vi.spyOn(client, "apiPost");

    const { postPlay } = await import("../devices");
    const result = await postPlay(validRequest);

    expect(result).toEqual({ status: "ok", device_name: "Living Room TV" });

    // Angua C1 — guard against a regression that bypasses apiPost (and therefore CSRF).
    expect(apiPostSpy).toHaveBeenCalledTimes(1);
    expect(apiPostSpy).toHaveBeenCalledWith("/api/play", validRequest);

    // CSRF header present in the outgoing fetch call (apiPost's responsibility, re-asserted here).
    const call = vi.mocked(fetch).mock.calls[0];
    const headers = call[1]?.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("test-csrf-value");

    // Body shape matches PlayRequest
    expect(JSON.parse(call[1]?.body as string)).toEqual(validRequest);
  });

  it("rejects with ApiAuthError on 401 (passes through — T4 picker will handle re-login)", async () => {
    mockFetch(401, { error: "jellyfin_auth_failed" });
    const { postPlay } = await import("../devices");

    await expect(postPlay(validRequest)).rejects.toThrow(ApiAuthError);
    await expect(postPlay(validRequest)).rejects.toHaveProperty("status", 401);
  });

  it("rejects with DeviceOfflineError on 409", async () => {
    mockFetch(409, { error: "device_offline" });
    const { postPlay } = await import("../devices");

    await expect(postPlay(validRequest)).rejects.toThrow(DeviceOfflineError);
    await expect(postPlay(validRequest)).rejects.toHaveProperty("status", 409);
  });

  it("rejects with PlaybackFailedError on 500", async () => {
    mockFetch(500, { error: "playback_failed" });
    const { postPlay } = await import("../devices");

    await expect(postPlay(validRequest)).rejects.toThrow(PlaybackFailedError);
    await expect(postPlay(validRequest)).rejects.toHaveProperty("status", 500);
  });

  it("rejects with PlaybackFailedError on any other non-ok non-auth status (e.g., 502)", async () => {
    mockFetch(502, { detail: "Bad gateway" });
    const { postPlay } = await import("../devices");

    await expect(postPlay(validRequest)).rejects.toThrow(PlaybackFailedError);
    await expect(postPlay(validRequest)).rejects.toHaveProperty("status", 502);
  });
});
