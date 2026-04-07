import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, toHaveNoViolations } from "jest-axe";

expect.extend(toHaveNoViolations);

// Mock next/navigation for LogoutButton
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Mock API client for LogoutButton
vi.mock("@/lib/api/client", () => ({
  apiPost: vi.fn(),
}));

// Mock auth context
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    userId: "u1",
    username: "alice",
    serverName: "MyServer",
    isAuthenticated: true,
    clearAuth: vi.fn(),
  }),
}));

import { HeaderContent } from "@/components/chat/header-content";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("HeaderContent", () => {
  it("renders app name", () => {
    render(<HeaderContent />);
    expect(screen.getByText("ai-movie-suggester")).toBeInTheDocument();
  });

  it("renders username from auth context", () => {
    render(<HeaderContent />);
    expect(screen.getByText("alice")).toBeInTheDocument();
  });

  it("renders 'New chat' button with aria-label when callback provided", () => {
    render(<HeaderContent onNewConversation={vi.fn()} />);
    const button = screen.getByRole("button", {
      name: /start new conversation/i,
    });
    expect(button).toBeInTheDocument();
    expect(button).toHaveTextContent("New chat");
  });

  it("renders logout button", () => {
    render(<HeaderContent />);
    expect(
      screen.getByRole("button", { name: /sign out/i })
    ).toBeInTheDocument();
  });

  it("'New conversation' button calls the onNewConversation callback", async () => {
    const user = userEvent.setup();
    const onNewConversation = vi.fn();
    render(<HeaderContent onNewConversation={onNewConversation} />);

    await user.click(
      screen.getByRole("button", { name: /start new conversation/i })
    );
    expect(onNewConversation).toHaveBeenCalledTimes(1);
  });

  it("passes axe accessibility audit", async () => {
    const { container } = render(<HeaderContent onNewConversation={vi.fn()} />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
