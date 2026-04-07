import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, toHaveNoViolations } from "jest-axe";
import { EmptyState } from "@/components/chat/empty-state";

expect.extend(toHaveNoViolations);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("EmptyState", () => {
  it("renders suggestion chips with expected text", () => {
    render(<EmptyState onSend={vi.fn()} />);
    expect(
      screen.getByText("Something like Alien but funny")
    ).toBeInTheDocument();
    expect(screen.getByText("A good movie for date night")).toBeInTheDocument();
    expect(
      screen.getByText("What's the best thriller in my library?")
    ).toBeInTheDocument();
  });

  it("clicking a chip calls onSend with the chip's text", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<EmptyState onSend={onSend} />);

    await user.click(screen.getByText("A good movie for date night"));
    expect(onSend).toHaveBeenCalledWith("A good movie for date night");
  });

  it("renders the tagline text", () => {
    render(<EmptyState onSend={vi.fn()} />);
    expect(
      screen.getByText(
        "Ask me for movie recommendations from your Jellyfin library"
      )
    ).toBeInTheDocument();
  });

  it("passes axe accessibility audit with zero violations", async () => {
    const { container } = render(<EmptyState onSend={vi.fn()} />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
