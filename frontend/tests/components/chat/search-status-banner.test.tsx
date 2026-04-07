import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, toHaveNoViolations } from "jest-axe";
import { SearchStatusBanner } from "@/components/chat/search-status-banner";

expect.extend(toHaveNoViolations);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SearchStatusBanner", () => {
  it("renders banner with correct text for 'no_embeddings'", () => {
    render(
      <SearchStatusBanner searchStatus="no_embeddings" onDismiss={vi.fn()} />
    );
    expect(
      screen.getByText(
        /your library is being indexed.*recommendations aren.*t available yet/i
      )
    ).toBeInTheDocument();
  });

  it("renders banner with correct text for 'partial_embeddings'", () => {
    render(
      <SearchStatusBanner
        searchStatus="partial_embeddings"
        onDismiss={vi.fn()}
      />
    );
    expect(
      screen.getByText(
        /your library is still being indexed.*some recommendations may be missing/i
      )
    ).toBeInTheDocument();
  });

  it("does not render for 'ok'", () => {
    const { container } = render(
      <SearchStatusBanner searchStatus="ok" onDismiss={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("does not render for undefined", () => {
    const { container } = render(
      <SearchStatusBanner searchStatus={undefined} onDismiss={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("close button calls onDismiss", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(
      <SearchStatusBanner searchStatus="no_embeddings" onDismiss={onDismiss} />
    );

    await user.click(screen.getByRole("button", { name: /dismiss banner/i }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("passes axe accessibility audit", async () => {
    const { container } = render(
      <SearchStatusBanner
        searchStatus="partial_embeddings"
        onDismiss={vi.fn()}
      />
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
