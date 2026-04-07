import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { CardCarousel } from "../card-carousel";
import type { SearchResultItem } from "@/lib/api/types";

function makeItem(id: string, title: string = "Movie"): SearchResultItem {
  return {
    jellyfin_id: id,
    title,
    overview: "A movie overview.",
    genres: ["Drama"],
    year: 2020,
    score: 0.8,
    poster_url: `/api/images/${id}`,
    community_rating: 7.0,
    runtime_minutes: 120,
  };
}

describe("CardCarousel", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders correct number of MovieCard children", () => {
    const items = [
      makeItem("id1", "Movie One"),
      makeItem("id2", "Movie Two"),
      makeItem("id3", "Movie Three"),
    ];
    render(<CardCarousel items={items} onCardClick={vi.fn()} />);

    expect(screen.getByText("Movie One")).toBeInTheDocument();
    expect(screen.getByText("Movie Two")).toBeInTheDocument();
    expect(screen.getByText("Movie Three")).toBeInTheDocument();
  });

  it("renders scroll indicator dots matching item count", () => {
    const items = [
      makeItem("id1", "Movie One"),
      makeItem("id2", "Movie Two"),
      makeItem("id3", "Movie Three"),
    ];
    const { container } = render(
      <CardCarousel items={items} onCardClick={vi.fn()} />
    );

    // Dots are spans inside a div with aria-hidden
    const dotsContainer = container.querySelector('[aria-hidden="true"]');
    expect(dotsContainer).not.toBeNull();
    const dots = dotsContainer!.querySelectorAll("span");
    expect(dots.length).toBe(3);
  });

  it("carousel container has scroll-snap CSS classes", () => {
    const items = [makeItem("id1"), makeItem("id2")];
    const { container } = render(
      <CardCarousel items={items} onCardClick={vi.fn()} />
    );

    const scrollContainer = container.querySelector(".snap-x");
    expect(scrollContainer).not.toBeNull();
    expect(scrollContainer!.className).toContain("snap-mandatory");
  });

  it("renders nothing when items is empty", () => {
    const { container } = render(
      <CardCarousel items={[]} onCardClick={vi.fn()} />
    );

    expect(container.innerHTML).toBe("");
  });

  it("does not render dots for single item", () => {
    const items = [makeItem("id1", "Solo Movie")];
    const { container } = render(
      <CardCarousel items={items} onCardClick={vi.fn()} />
    );

    // No dots when only 1 item
    const dotsContainer = container.querySelector('[aria-hidden="true"]');
    expect(dotsContainer).toBeNull();
  });
});
