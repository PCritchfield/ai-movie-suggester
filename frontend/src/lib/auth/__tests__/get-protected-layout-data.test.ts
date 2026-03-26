import { describe, it, expect, vi, afterEach } from "vitest";
import { ApiAuthError } from "@/lib/api/types";

vi.mock("@/lib/api/server", () => ({
  serverGet: vi.fn(),
}));

describe("getProtectedLayoutData", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns success with mapped user on 200", async () => {
    const { serverGet } = await import("@/lib/api/server");
    vi.mocked(serverGet).mockResolvedValue({
      user_id: "u1",
      username: "alice",
      server_name: "Srv",
    });
    const { getProtectedLayoutData } =
      await import("../get-protected-layout-data");
    const result = await getProtectedLayoutData();
    expect(result).toEqual({
      type: "success",
      user: { userId: "u1", username: "alice", serverName: "Srv" },
    });
  });

  it("returns redirect on ApiAuthError (401)", async () => {
    const { serverGet } = await import("@/lib/api/server");
    vi.mocked(serverGet).mockRejectedValue(new ApiAuthError(401, {}));
    const { getProtectedLayoutData } =
      await import("../get-protected-layout-data");
    const result = await getProtectedLayoutData();
    expect(result).toEqual({
      type: "redirect",
      url: "/login?reason=session_expired",
    });
  });

  it("returns redirect on network error", async () => {
    const { serverGet } = await import("@/lib/api/server");
    vi.mocked(serverGet).mockRejectedValue(new TypeError("fetch failed"));
    const { getProtectedLayoutData } =
      await import("../get-protected-layout-data");
    const result = await getProtectedLayoutData();
    expect(result).toEqual({
      type: "redirect",
      url: "/login?reason=session_expired",
    });
  });
});
