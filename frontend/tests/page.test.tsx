import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import Home from "@/app/page";

test("home page renders heading", () => {
  render(<Home />);
  expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
});

test("home page displays project name", () => {
  render(<Home />);
  const elements = screen.getAllByText(/ai-movie-suggester/i);
  expect(elements.length).toBeGreaterThan(0);
});
