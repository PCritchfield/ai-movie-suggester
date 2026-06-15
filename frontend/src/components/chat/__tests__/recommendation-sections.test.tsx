import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { RecommendationSections } from "../recommendation-sections";
import type { PickItem, SearchResultItem } from "@/lib/api/types";

afterEach(() => cleanup());

function rec(jellyfin_id: string, title: string): SearchResultItem {
  return {
    jellyfin_id,
    title,
    overview: null,
    genres: [],
    year: null,
    score: 0.8,
    poster_url: `/p/${jellyfin_id}`,
    community_rating: null,
    runtime_minutes: null,
    jellyfin_web_url: null,
  };
}

const RECS = [
  rec("a1", "Alien"),
  rec("g1", "Galaxy Quest"),
  rec("t1", "The Thing"),
  rec("p1", "Predator"),
];

const PICKS: PickItem[] = [
  { jellyfin_id: "g1", reasoning: "funny", pick_order: 1 },
  { jellyfin_id: "a1", reasoning: "scary", pick_order: 2 },
];

describe("RecommendationSections", () => {
  it("renders a Recommended section and a collapsed More matches disclosure", () => {
    render(
      <RecommendationSections
        recommendations={RECS}
        picks={PICKS}
        onCardClick={vi.fn()}
      />
    );

    // Recommended label present, with aria-live scoped to the label only.
    const label = screen.getByText("Recommended");
    expect(label).toHaveAttribute("aria-live", "polite");

    // The "More matches" disclosure is collapsed by default and counts the rest.
    const summary = screen.getByText(/More matches \(2\)/);
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
  });

  it("shows picks in LLM order and the unpicked rest under the disclosure", () => {
    render(
      <RecommendationSections
        recommendations={RECS}
        picks={PICKS}
        onCardClick={vi.fn()}
      />
    );

    // Pick badges appear for the recommended cards (one ★ Pick per pick).
    expect(screen.getAllByText("★ Pick")).toHaveLength(2);

    // Recommended cards are Galaxy Quest (order 1) then Alien (order 2).
    const recButtons = screen.getAllByLabelText(/View details for/);
    const recommendedTitles = recButtons
      .map((b) => b.getAttribute("aria-label"))
      .filter((l) => l?.includes("Galaxy Quest") || l?.includes("Alien"));
    expect(recommendedTitles[0]).toContain("Galaxy Quest");
    expect(recommendedTitles[1]).toContain("Alien");

    // The rest (The Thing, Predator) are present (inside the disclosure).
    expect(screen.getByLabelText("View details for The Thing")).toBeTruthy();
    expect(screen.getByLabelText("View details for Predator")).toBeTruthy();
  });

  it("falls back to a single plain carousel when no picks resolve", () => {
    render(
      <RecommendationSections
        recommendations={RECS}
        picks={[{ jellyfin_id: "UNKNOWN", reasoning: "x", pick_order: 1 }]}
        onCardClick={vi.fn()}
      />
    );
    // No Recommended label, no badges — just the plain candidate cards.
    expect(screen.queryByText("Recommended")).toBeNull();
    expect(screen.queryByText("★ Pick")).toBeNull();
    expect(screen.getAllByLabelText(/View details for/)).toHaveLength(4);
  });
});
