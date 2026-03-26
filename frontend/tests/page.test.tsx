import { expect, test, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AuthProvider } from "@/lib/auth/auth-context";
import { AuthHome } from "@/components/auth-home";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  apiPost: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("protected page renders username and server name", () => {
  render(
    <AuthProvider userId="u1" username="alice" serverName="MyServer">
      <AuthHome />
    </AuthProvider>,
  );
  expect(screen.getByText("alice")).toBeInTheDocument();
  expect(screen.getByText(/MyServer/)).toBeInTheDocument();
});

test("protected page renders logout button", () => {
  render(
    <AuthProvider userId="u1" username="alice" serverName="MyServer">
      <AuthHome />
    </AuthProvider>,
  );
  expect(
    screen.getByRole("button", { name: /sign out/i }),
  ).toBeInTheDocument();
});
