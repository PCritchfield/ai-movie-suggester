import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, afterEach } from "vitest";
import { axe, toHaveNoViolations } from "jest-axe";
import { CardDetail } from "../card-detail";
import type { SearchResultItem } from "@/lib/api/types";

expect.extend(toHaveNoViolations);

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
