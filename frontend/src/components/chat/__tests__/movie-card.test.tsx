import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, afterEach } from "vitest";
import { axe, toHaveNoViolations } from "jest-axe";
import { MovieCard } from "../movie-card";
import type { SearchResultItem } from "@/lib/api/types";

expect.extend(toHaveNoViolations);

function makeItem(overrides: Partial<SearchResultItem> = {}): SearchResultItem {
  return {
    jellyfin_id: "abc123def456abc123def456abc123de",
    title: "Galaxy Quest",
    overview:
      "A comedy about sci-fi actors who find themselves in a real space adventure.",
    genres: ["Comedy", "Sci-Fi"],
    year: 1999,
    score: 0.85,
    poster_url: "/api/images/abc123def456abc123def456abc123de",
    community_rating: 7.4,
    runtime_minutes: 102,
    jellyfin_web_url: null,
    ...overrides,
  };
}

describe("MovieCard", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders title, year, overview, and genres", () => {
    render(<MovieCard item={makeItem()} onClick={vi.fn()} />);

    expect(screen.getByText("Galaxy Quest")).toBeInTheDocument();
    expect(screen.getByText("(1999)")).toBeInTheDocument();
    expect(screen.getByText(/comedy about sci-fi actors/)).toBeInTheDocument();
    expect(screen.getByText("Comedy")).toBeInTheDocument();
    expect(screen.getByText("Sci-Fi")).toBeInTheDocument();
  });

  it("truncates overview with line-clamp", () => {
    render(<MovieCard item={makeItem()} onClick={vi.fn()} />);

    const overview = screen.getByText(/comedy about sci-fi actors/);
    expect(overview.className).toContain("line-clamp-3");
  });

  it("shows only first 3 genres when item has more", () => {
    const item = makeItem({
      genres: ["Action", "Comedy", "Drama", "Horror", "Sci-Fi"],
    });
    render(<MovieCard item={item} onClick={vi.fn()} />);

    expect(screen.getByText("Action")).toBeInTheDocument();
    expect(screen.getByText("Comedy")).toBeInTheDocument();
    expect(screen.getByText("Drama")).toBeInTheDocument();
    expect(screen.queryByText("Horror")).not.toBeInTheDocument();
    expect(screen.queryByText("Sci-Fi")).not.toBeInTheDocument();
  });

  it("poster img has correct alt text", () => {
    render(<MovieCard item={makeItem()} onClick={vi.fn()} />);

    const img = screen.getByAltText("Galaxy Quest (1999)");
    expect(img).toBeInTheDocument();
  });

  it("poster img has loading=lazy", () => {
    render(<MovieCard item={makeItem()} onClick={vi.fn()} />);

    const img = screen.getByAltText("Galaxy Quest (1999)");
    expect(img).toHaveAttribute("loading", "lazy");
  });

  it("calls onClick when card is clicked", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<MovieCard item={makeItem()} onClick={onClick} />);

    await user.click(
      screen.getByRole("button", { name: /View details for Galaxy Quest/ })
    );
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("calls onClick on Enter keypress via native button", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<MovieCard item={makeItem()} onClick={onClick} />);

    const button = screen.getByRole("button", {
      name: /View details for Galaxy Quest/,
    });
    button.focus();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("shows PosterPlaceholder when image fires onError", () => {
    render(<MovieCard item={makeItem()} onClick={vi.fn()} />);

    const img = screen.getByAltText("Galaxy Quest (1999)");
    fireEvent.error(img);

    // After error, the image should be replaced with placeholder
    expect(
      screen.queryByAltText("Galaxy Quest (1999)")
    ).not.toBeInTheDocument();
    // The placeholder shows the title
    expect(screen.getAllByText("Galaxy Quest").length).toBeGreaterThanOrEqual(
      1
    );
  });

  it("passes axe accessibility audit", async () => {
    const { container } = render(
      <MovieCard item={makeItem()} onClick={vi.fn()} />
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
