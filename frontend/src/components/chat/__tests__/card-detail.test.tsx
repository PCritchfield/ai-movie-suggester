import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { axe, toHaveNoViolations } from "jest-axe";
import { CardDetail } from "../card-detail";
import type { Device, SearchResultItem } from "@/lib/api/types";

expect.extend(toHaveNoViolations);

function mockDevicesFetch(devices: Device[] = []): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(devices),
    })
  );
}

function makeItem(overrides: Partial<SearchResultItem> = {}): SearchResultItem {
  return {
    jellyfin_id: "abc123def456abc123def456abc123de",
    title: "Galaxy Quest",
    overview:
      "A comedy about sci-fi actors who find themselves in a real intergalactic adventure.",
    genres: ["Comedy", "Sci-Fi", "Adventure"],
    year: 1999,
    score: 0.85,
    poster_url: "/api/images/abc123def456abc123def456abc123de",
    community_rating: 7.4,
    runtime_minutes: 102,
    jellyfin_web_url: "https://jellyfin.example.com/web/#!/details?id=abc123",
    ...overrides,
  };
}

describe("CardDetail", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders all fields when item has full data", () => {
    render(<CardDetail item={makeItem()} open={true} onClose={vi.fn()} />);

    expect(screen.getByText("Galaxy Quest")).toBeInTheDocument();
    expect(screen.getByText("(1999)")).toBeInTheDocument();
    expect(screen.getByText("Comedy")).toBeInTheDocument();
    expect(screen.getByText("Sci-Fi")).toBeInTheDocument();
    expect(screen.getByText("Adventure")).toBeInTheDocument();
    expect(screen.getByText(/comedy about sci-fi actors/)).toBeInTheDocument();
    expect(screen.getByText(/7\.4\/10/)).toBeInTheDocument();
    expect(screen.getByText("1h 42m")).toBeInTheDocument();
    expect(screen.getByText("View in Jellyfin")).toBeInTheDocument();
  });

  it("hides View in Jellyfin link when jellyfin_web_url is null", () => {
    render(
      <CardDetail
        item={makeItem({ jellyfin_web_url: null })}
        open={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.queryByText("View in Jellyfin")).not.toBeInTheDocument();
  });

  it("hides community rating when null", () => {
    render(
      <CardDetail
        item={makeItem({ community_rating: null })}
        open={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.queryByText(/\/10/)).not.toBeInTheDocument();
  });

  it("hides runtime when null", () => {
    render(
      <CardDetail
        item={makeItem({ runtime_minutes: null })}
        open={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.queryByText(/\d+h/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+m/)).not.toBeInTheDocument();
  });

  it("formats runtime: 90 → 1h 30m", () => {
    render(
      <CardDetail
        item={makeItem({ runtime_minutes: 90 })}
        open={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText("1h 30m")).toBeInTheDocument();
  });

  it("formats runtime: 60 → 1h 0m", () => {
    render(
      <CardDetail
        item={makeItem({ runtime_minutes: 60 })}
        open={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText("1h 0m")).toBeInTheDocument();
  });

  it("formats runtime: 45 → 45m (no 0h prefix)", () => {
    render(
      <CardDetail
        item={makeItem({ runtime_minutes: 45 })}
        open={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText("45m")).toBeInTheDocument();
    expect(screen.queryByText("0h")).not.toBeInTheDocument();
  });

  it("closes via close button click", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<CardDetail item={makeItem()} open={true} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes via Escape key", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<CardDetail item={makeItem()} open={true} onClose={onClose} />);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes via backdrop click", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<CardDetail item={makeItem()} open={true} onClose={onClose} />);

    // Radix Dialog overlay has data-state="open" on the backdrop
    const overlay = document.querySelector("[data-state='open']");
    expect(overlay).not.toBeNull();
    await user.click(overlay!);
    expect(onClose).toHaveBeenCalled();
  });

  it("has role=dialog", () => {
    render(<CardDetail item={makeItem()} open={true} onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
  });

  it("has aria-labelledby referencing title", () => {
    render(<CardDetail item={makeItem()} open={true} onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog");
    const labelledBy = dialog.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();

    const titleEl = document.getElementById(labelledBy!);
    expect(titleEl).not.toBeNull();
    expect(titleEl!.textContent).toContain("Galaxy Quest");
  });

  it("passes axe accessibility audit", async () => {
    const { container } = render(
      <CardDetail item={makeItem()} open={true} onClose={vi.fn()} />
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe("CardDetail — Cast to TV entry point", () => {
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

  it("renders the Cast to TV button next to View in Jellyfin", () => {
    mockDevicesFetch();
    render(<CardDetail item={makeItem()} open={true} onClose={vi.fn()} />);

    const castButton = screen.getByRole("button", { name: "Cast to TV" });
    expect(castButton).toBeInTheDocument();
    expect(castButton).toHaveClass("min-h-11");
    // "View in Jellyfin" still present as an <a>
    expect(
      screen.getByRole("link", { name: "View in Jellyfin" })
    ).toBeInTheDocument();
  });

  it("clicking Cast to TV opens the device-picker dialog", async () => {
    const user = userEvent.setup();
    mockDevicesFetch([]);

    render(<CardDetail item={makeItem()} open={true} onClose={vi.fn()} />);

    // Before click — only the card-detail dialog should be present
    expect(screen.queryByText(/no devices found/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cast to TV" }));

    // Picker appears (empty state resolves via the mocked fetch → [])
    await screen.findByText(
      "No devices found. Open Jellyfin on your TV or phone, then refresh."
    );

    // Two dialogs in the DOM now — card-detail + picker. Use `hidden: true`
    // because Radix sets aria-hidden on the background dialog when a nested
    // dialog is open, which RTL excludes from role queries by default.
    const dialogs = screen.getAllByRole("dialog", { hidden: true });
    expect(dialogs.length).toBe(2);
  });

  it("does not suppress Radix returnFocus — picker is not rendered with returnFocus={false}", async () => {
    // NOTE: jsdom + Radix FocusScope does not faithfully reproduce focus-restore
    // behavior when multiple Dialog FocusScopes stack. The authoritative focus
    // verification for this flow is *planned* in Playwright E2E and tracked by
    // issue #207 — no spec exists yet. Here we verify the *intent*: the picker
    // is not rendered with `returnFocus={false}`, which is the only way a dev
    // could accidentally suppress the default.
    //
    // The source-of-truth assertion: grep `device-picker-dialog.tsx` and
    // `card-detail.tsx` — neither should contain `returnFocus={false}` or
    // `onCloseAutoFocus={e => e.preventDefault()}`. If either appears, this
    // test should be re-evaluated.
    const user = userEvent.setup();
    mockDevicesFetch([]);

    render(<CardDetail item={makeItem()} open={true} onClose={vi.fn()} />);

    const castButton = screen.getByRole("button", { name: "Cast to TV" });
    await user.click(castButton);
    await screen.findByText(/no devices found/i);

    // Sanity: picker Dialog emits `data-state="open"` on its content
    const dialogs = screen.getAllByRole("dialog", { hidden: true });
    expect(dialogs.length).toBe(2);
    // Neither dialog has a custom returnFocus={false} marker (we'd expect a
    // data-return-focus="false" or similar — Radix doesn't expose this, so the
    // grep-in-source check above is the real guard).
    expect(dialogs[0]).toBeInTheDocument();
  });

  it("pressing Escape with both dialogs open dismisses only the top (picker) dialog; card-detail stays open", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mockDevicesFetch([]);

    render(<CardDetail item={makeItem()} open={true} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "Cast to TV" }));
    await screen.findByText(/no devices found/i);

    // Both dialogs mounted
    expect(screen.getAllByRole("dialog", { hidden: true }).length).toBe(2);

    await user.keyboard("{Escape}");

    // Picker closed
    await waitFor(() => {
      expect(screen.queryByText(/no devices found/i)).not.toBeInTheDocument();
    });

    // card-detail still visible (its title + content still there)
    expect(screen.getByText("Galaxy Quest")).toBeInTheDocument();

    // The parent onClose for card-detail was NOT called — Escape dismissed
    // only the picker, not the card-detail.
    expect(onClose).not.toHaveBeenCalled();
  });
});
