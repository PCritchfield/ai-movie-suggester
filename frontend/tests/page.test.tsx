import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// Mock useChat hook
vi.mock("@/hooks/use-chat", () => ({
  useChat: () => ({
    messages: [],
    isStreaming: false,
    error: null,
    sendMessage: vi.fn(),
    clearHistory: vi.fn(),
    retry: vi.fn(),
  }),
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

// Mock next/navigation for LogoutButton
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// Mock API client for LogoutButton
vi.mock("@/lib/api/client", () => ({
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
}));

// Mock react-markdown to avoid ESM issues in test
vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => children,
}));

import ChatPage from "@/app/(protected)/page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ChatPage", () => {
  it("renders header with app name and username", () => {
    render(<ChatPage />);
    expect(screen.getByText("ai-movie-suggester")).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
  });

  it("renders empty state with suggestion chips when no messages", () => {
    render(<ChatPage />);
    expect(
      screen.getByText("Something like Alien but funny")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Ask me for movie recommendations from your Jellyfin library"
      )
    ).toBeInTheDocument();
  });

  it("renders chat input", () => {
    render(<ChatPage />);
    expect(screen.getByLabelText(/chat message/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /send message/i })
    ).toBeInTheDocument();
  });
});
