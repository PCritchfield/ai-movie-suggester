import { render, screen, cleanup, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DevicePickerDialog } from "../device-picker-dialog";
import type { Device, SearchResultItem } from "@/lib/api/types";

function makeItem(overrides: Partial<SearchResultItem> = {}): SearchResultItem {
  return {
    jellyfin_id: "abc123def456abc123def456abc123de",
    title: "Galaxy Quest",
    overview: "A comedy about sci-fi actors.",
    genres: ["Comedy", "Sci-Fi"],
    year: 1999,
    score: 0.85,
    poster_url: "/api/images/abc123",
    community_rating: 7.4,
    runtime_minutes: 102,
    jellyfin_web_url: "https://jellyfin.example.com/web",
    ...overrides,
  };
}

function makeDevice(overrides: Partial<Device> = {}): Device {
  return {
    session_id: "session-1",
    name: "Living Room TV",
    client: "Jellyfin Android TV",
    device_type: "Tv",
    ...overrides,
  };
}

function mockFetchOnce(status: number, body: unknown) {
  return vi.fn().mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

function mockFetchResponses(
  ...responses: Array<{ status: number; body: unknown }>
) {
  const fn = vi.fn();
  for (const { status, body } of responses) {
    fn.mockResolvedValueOnce({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    });
  }
  return fn;
}

describe("DevicePickerDialog — fetch states", () => {
  beforeEach(() => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "csrf_token=test-csrf-value",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
    document.cookie = "";
  });

  it("renders Loading state (role=status) while fetch is in flight when open", () => {
    // Never-resolving fetch so loading state persists for assertion
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => new Promise(() => {}))
    );

    render(
      <DevicePickerDialog
        item={makeItem()}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    // Loading skeleton / progress indicator is present
    expect(
      screen.getByRole("status", { name: /loading devices/i })
    ).toBeInTheDocument();
  });

  it("renders populated List with device rows (name + client, Lucide icon, 44px min-height, correct aria-label)", async () => {
    const devices: Device[] = [
      makeDevice({
        session_id: "s1",
        name: "Living Room TV",
        client: "Jellyfin Android TV",
        device_type: "Tv",
      }),
      makeDevice({
        session_id: "s2",
        name: "Phone",
        client: "Jellyfin Mobile",
        device_type: "Mobile",
      }),
    ];
    vi.stubGlobal("fetch", mockFetchOnce(200, devices));

    render(
      <DevicePickerDialog
        item={makeItem({ title: "Galaxy Quest" })}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    // Each device shows up as a real <button> with the canonical aria-label
    const tvButton = await screen.findByRole("button", {
      name: "Cast Galaxy Quest to Living Room TV, Jellyfin Android TV",
    });
    const phoneButton = await screen.findByRole("button", {
      name: "Cast Galaxy Quest to Phone, Jellyfin Mobile",
    });

    expect(tvButton).toBeInTheDocument();
    expect(phoneButton).toBeInTheDocument();

    // Min 44px tap height (Tailwind min-h-11 = 44px)
    expect(tvButton).toHaveClass("min-h-11");

    // Both lines are visible in DOM text content
    expect(tvButton.textContent).toContain("Living Room TV");
    expect(tvButton.textContent).toContain("Jellyfin Android TV");
    expect(tvButton.textContent).toContain("Tv");

    // Lucide icon is rendered for the row (Tv type → Tv icon — any svg marker works for verification)
    const svg = tvButton.querySelector("svg");
    expect(svg).not.toBeNull();
  });

  it("renders the Empty state with exact copy + prominent text-labeled Refresh", async () => {
    vi.stubGlobal("fetch", mockFetchOnce(200, []));

    render(
      <DevicePickerDialog
        item={makeItem()}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    await screen.findByText(
      "No devices found. Open Jellyfin on your TV or phone, then refresh."
    );

    const refresh = screen.getByRole("button", { name: "Refresh" });
    expect(refresh).toBeInTheDocument();
    // Prominent text-labeled button, not icon-only — at least 44px tap, visible "Refresh" text
    expect(refresh.textContent).toContain("Refresh");
    expect(refresh).toHaveClass("min-h-11");
  });

  it("renders the Fetch-error state with exact copy + Refresh on non-auth failure", async () => {
    vi.stubGlobal("fetch", mockFetchOnce(500, { detail: "Server error" }));

    render(
      <DevicePickerDialog
        item={makeItem()}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    await screen.findByText("Couldn't load devices. Try again.");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });

  it("refreshing in Empty state re-invokes fetch and shows new devices", async () => {
    const user = userEvent.setup();
    const fresh = [makeDevice({ session_id: "fresh", name: "Fresh TV" })];
    vi.stubGlobal(
      "fetch",
      mockFetchResponses(
        { status: 200, body: [] },
        { status: 200, body: fresh }
      )
    );

    render(
      <DevicePickerDialog
        item={makeItem({ title: "Galaxy Quest" })}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    // Initial empty state
    await screen.findByText(/no devices found/i);

    await user.click(screen.getByRole("button", { name: "Refresh" }));

    // Fresh device row appears
    await screen.findByRole("button", {
      name: "Cast Galaxy Quest to Fresh TV, Jellyfin Android TV",
    });
  });

  it("reopening while a prior fetch is still in-flight applies only the latest result (fetchId race guard)", async () => {
    // First open's fetch never resolves until we call resolveFirst;
    // second open's fetch resolves immediately with freshDevice.
    // Then we resolve the stalled first fetch with staleDevice — the guard
    // must drop it on the floor so the list continues to show freshDevice.

    type MockResponse = {
      ok: boolean;
      status: number;
      json: () => Promise<unknown>;
    };
    let resolveFirst: (r: MockResponse) => void = () => {};
    const firstFetch = new Promise<MockResponse>((resolve) => {
      resolveFirst = resolve;
    });

    const staleDevice = [makeDevice({ session_id: "stale", name: "Stale TV" })];
    const freshDevice = [makeDevice({ session_id: "fresh", name: "Fresh TV" })];

    const fetchFn = vi
      .fn()
      .mockImplementationOnce(() => firstFetch)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(freshDevice),
      });
    vi.stubGlobal("fetch", fetchFn);

    const item = makeItem({ title: "Galaxy Quest" });
    const onClose = vi.fn();
    const onDispatched = vi.fn();

    const { rerender } = render(
      <DevicePickerDialog
        item={item}
        open={true}
        onClose={onClose}
        onDispatched={onDispatched}
      />
    );

    // First fetch is hanging. Close + reopen to trigger a second fetch.
    rerender(
      <DevicePickerDialog
        item={item}
        open={false}
        onClose={onClose}
        onDispatched={onDispatched}
      />
    );
    rerender(
      <DevicePickerDialog
        item={item}
        open={true}
        onClose={onClose}
        onDispatched={onDispatched}
      />
    );

    // Second fetch resolves with fresh device
    await screen.findByRole("button", {
      name: /Fresh TV/i,
    });

    // Now resolve the stalled first fetch with stale data — guard must drop it
    await act(async () => {
      resolveFirst({
        ok: true,
        status: 200,
        json: () => Promise.resolve(staleDevice),
      });
      await Promise.resolve();
    });

    expect(screen.queryByRole("button", { name: /Stale TV/i })).toBeNull();
    expect(
      screen.getByRole("button", { name: /Fresh TV/i })
    ).toBeInTheDocument();
  });

  it("fetches fresh devices on each open false→true transition", async () => {
    const fetchFn = mockFetchResponses(
      {
        status: 200,
        body: [makeDevice({ session_id: "a", name: "First Open TV" })],
      },
      {
        status: 200,
        body: [makeDevice({ session_id: "b", name: "Second Open TV" })],
      }
    );
    vi.stubGlobal("fetch", fetchFn);

    const { rerender } = render(
      <DevicePickerDialog
        item={makeItem({ title: "Galaxy Quest" })}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    await screen.findByRole("button", {
      name: /First Open TV/i,
    });

    // Close
    rerender(
      <DevicePickerDialog
        item={makeItem({ title: "Galaxy Quest" })}
        open={false}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    // Reopen → should fetch again, show fresh list
    rerender(
      <DevicePickerDialog
        item={makeItem({ title: "Galaxy Quest" })}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    await screen.findByRole("button", {
      name: /Second Open TV/i,
    });

    // Initial fetch was called at least twice (Strict Mode may double-invoke, which is tolerated)
    expect(fetchFn.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});

describe("DevicePickerDialog — Lucide icon mapping", () => {
  beforeEach(() => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "csrf_token=test-csrf-value",
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
    document.cookie = "";
  });

  it.each([
    ["Tv", "tv"],
    ["Mobile", "smartphone"],
    ["Tablet", "tablet"],
    ["Other", "monitor-smartphone"],
  ] as const)(
    "renders Lucide %s → lucide-%s icon for a device of that type",
    async (deviceType, iconClassName) => {
      vi.stubGlobal(
        "fetch",
        mockFetchOnce(200, [
          makeDevice({
            session_id: "s",
            name: `${deviceType} device`,
            device_type: deviceType,
          }),
        ])
      );

      render(
        <DevicePickerDialog
          item={makeItem({ title: "Galaxy Quest" })}
          open={true}
          onClose={vi.fn()}
          onDispatched={vi.fn()}
        />
      );

      const button = await screen.findByRole("button", {
        name: new RegExp(`Cast Galaxy Quest to ${deviceType} device`, "i"),
      });
      const svg = button.querySelector("svg");
      expect(svg).not.toBeNull();
      // Lucide adds a "lucide-<name>" class on its svg root
      expect(svg!.getAttribute("class") || "").toContain(
        `lucide-${iconClassName}`
      );
    }
  );
});

describe("DevicePickerDialog — Dispatching state and concurrent-dispatch guard", () => {
  beforeEach(() => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "csrf_token=test-csrf-value",
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
    document.cookie = "";
  });

  it("shows inline spinner on tapped row and disables other rows during dispatch (T2 stub: never-resolving onDispatched)", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      mockFetchOnce(200, [
        makeDevice({ session_id: "tv", name: "TV" }),
        makeDevice({
          session_id: "phone",
          name: "Phone",
          device_type: "Mobile",
          client: "Jellyfin Mobile",
        }),
      ])
    );

    // Never-resolving onDispatched pins the component in the dispatching state for the assertion
    const onDispatched = vi.fn(() => new Promise<void>(() => {}));

    render(
      <DevicePickerDialog
        item={makeItem({ title: "Galaxy Quest" })}
        open={true}
        onClose={vi.fn()}
        onDispatched={onDispatched}
      />
    );

    const tvButton = await screen.findByRole("button", {
      name: "Cast Galaxy Quest to TV, Jellyfin Android TV",
    });
    const phoneButton = await screen.findByRole("button", {
      name: "Cast Galaxy Quest to Phone, Jellyfin Mobile",
    });

    await user.click(tvButton);

    // Tapped row has a spinner (role=status with dispatching label)
    await waitFor(() => {
      expect(
        screen.getByRole("status", { name: /dispatching to tv/i })
      ).toBeInTheDocument();
    });

    // Other rows disabled while dispatch in flight
    expect(phoneButton).toBeDisabled();
  });

  it("concurrent-dispatch guard: a second tap during an in-flight dispatch is a no-op (postPlay not re-called)", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      mockFetchOnce(200, [
        makeDevice({ session_id: "tv", name: "TV" }),
        makeDevice({
          session_id: "phone",
          name: "Phone",
          device_type: "Mobile",
          client: "Jellyfin Mobile",
        }),
      ])
    );

    const onDispatched = vi.fn(() => new Promise<void>(() => {}));

    render(
      <DevicePickerDialog
        item={makeItem({ title: "Galaxy Quest" })}
        open={true}
        onClose={vi.fn()}
        onDispatched={onDispatched}
      />
    );

    const tvButton = await screen.findByRole("button", {
      name: "Cast Galaxy Quest to TV, Jellyfin Android TV",
    });
    const phoneButton = await screen.findByRole("button", {
      name: "Cast Galaxy Quest to Phone, Jellyfin Mobile",
    });

    await user.click(tvButton);
    // Second tap on the other row — must be ignored because first dispatch is in flight
    await user.click(phoneButton);

    // onDispatched called exactly once, with the first device's name
    expect(onDispatched).toHaveBeenCalledTimes(1);
    expect(onDispatched).toHaveBeenCalledWith("TV");
  });
});

describe("DevicePickerDialog — Offline banner rendering (test-only forceOffline)", () => {
  beforeEach(() => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "csrf_token=test-csrf-value",
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
    document.cookie = "";
  });

  it("renders offline banner with aria-live=assertive and exact copy when forceOffline is true", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchOnce(200, [makeDevice({ session_id: "tv", name: "TV" })])
    );

    render(
      <DevicePickerDialog
        item={makeItem()}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
        forceOffline={true}
      />
    );

    const banner = await screen.findByText(
      "That device just went offline — pick another"
    );
    expect(banner).toBeInTheDocument();

    // aria-live="assertive" on the banner (or an enclosing element)
    const liveRegion = banner.closest('[aria-live="assertive"]');
    expect(liveRegion).not.toBeNull();
  });

  it("does NOT render offline banner when forceOffline is false/undefined", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchOnce(200, [makeDevice({ session_id: "tv", name: "TV" })])
    );

    render(
      <DevicePickerDialog
        item={makeItem()}
        open={true}
        onClose={vi.fn()}
        onDispatched={vi.fn()}
      />
    );

    // Wait for the list to load so we know we're past initial render
    await screen.findByRole("button", { name: /Cast .* to TV/i });
    expect(
      screen.queryByText("That device just went offline — pick another")
    ).toBeNull();
  });
});
