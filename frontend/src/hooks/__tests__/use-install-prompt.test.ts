import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useInstallPrompt } from "../use-install-prompt";

// Helper to set up window state
function mockStandalone(value: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches:
        value &&
        (query === "(display-mode: standalone)" ||
          query === "(display-mode: minimal-ui)"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
}

function mockUserAgent(ua: string) {
  Object.defineProperty(navigator, "userAgent", {
    writable: true,
    value: ua,
    configurable: true,
  });
}

function mockPlatform(platform: string) {
  Object.defineProperty(navigator, "platform", {
    writable: true,
    value: platform,
    configurable: true,
  });
}

function mockMaxTouchPoints(points: number) {
  Object.defineProperty(navigator, "maxTouchPoints", {
    writable: true,
    value: points,
    configurable: true,
  });
}

describe("useInstallPrompt", () => {
  beforeEach(() => {
    localStorage.clear();
    mockStandalone(false);
    // Default to a desktop Chrome-like UA
    mockUserAgent(
      "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"
    );
    mockPlatform("Linux armv81");
    mockMaxTouchPoints(5);
  });

  describe("Android / beforeinstallprompt", () => {
    it("captures beforeinstallprompt event and enables prompt", async () => {
      const { result } = renderHook(() => useInstallPrompt());

      // Before event fires, platform is unsupported (no proof of Android yet)
      expect(result.current.platform).toBe("unsupported");
      expect(result.current.canPrompt).toBe(false);

      // Simulate the browser firing beforeinstallprompt
      const mockEvent = new Event("beforeinstallprompt");
      Object.assign(mockEvent, {
        prompt: vi.fn().mockResolvedValue(undefined),
        userChoice: Promise.resolve({ outcome: "dismissed" as const }),
      });

      await act(async () => {
        window.dispatchEvent(mockEvent);
      });

      expect(result.current.canPrompt).toBe(true);
      expect(result.current.platform).toBe("android");
    });

    it("calls prompt() on the deferred event", async () => {
      const { result } = renderHook(() => useInstallPrompt());

      const promptFn = vi.fn().mockResolvedValue(undefined);
      const mockEvent = new Event("beforeinstallprompt");
      Object.assign(mockEvent, {
        prompt: promptFn,
        userChoice: Promise.resolve({ outcome: "accepted" as const }),
      });

      await act(async () => {
        window.dispatchEvent(mockEvent);
      });

      await act(async () => {
        await result.current.prompt();
      });

      expect(promptFn).toHaveBeenCalledOnce();
      // After acceptance, banner hides
      expect(result.current.canPrompt).toBe(false);
    });
  });

  describe("iOS Safari detection", () => {
    it("detects iOS Safari and sets platform to ios", () => {
      mockUserAgent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
      );
      mockPlatform("iPhone");

      const { result } = renderHook(() => useInstallPrompt());

      expect(result.current.platform).toBe("ios");
      expect(result.current.canPrompt).toBe(true);
    });

    it("detects iPad with maxTouchPoints as iOS", () => {
      mockUserAgent(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
      );
      mockPlatform("MacIntel");
      mockMaxTouchPoints(5);

      const { result } = renderHook(() => useInstallPrompt());

      expect(result.current.platform).toBe("ios");
      expect(result.current.canPrompt).toBe(true);
    });
  });

  describe("already installed", () => {
    it("returns canPrompt false when in standalone mode", () => {
      mockStandalone(true);

      const { result } = renderHook(() => useInstallPrompt());

      expect(result.current.canPrompt).toBe(false);
    });
  });

  describe("dismissal persistence", () => {
    it("persists dismissal to localStorage", async () => {
      mockUserAgent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
      );
      mockPlatform("iPhone");

      const { result } = renderHook(() => useInstallPrompt());

      expect(result.current.canPrompt).toBe(true);

      act(() => {
        result.current.dismiss();
      });

      expect(result.current.canPrompt).toBe(false);
      expect(localStorage.getItem("pwa-install-dismissed")).toBe("true");
    });

    it("returns canPrompt false when previously dismissed", () => {
      localStorage.setItem("pwa-install-dismissed", "true");
      mockUserAgent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
      );
      mockPlatform("iPhone");

      const { result } = renderHook(() => useInstallPrompt());

      expect(result.current.canPrompt).toBe(false);
    });
  });

  describe("unsupported browser", () => {
    it("returns canPrompt false for non-supported browsers", () => {
      mockUserAgent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
      );
      mockPlatform("Win32");

      const { result } = renderHook(() => useInstallPrompt());

      expect(result.current.canPrompt).toBe(false);
      expect(result.current.platform).toBe("unsupported");
    });
  });
});
