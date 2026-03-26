import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, act } from "@testing-library/react";
import { AuthProvider, useAuth } from "../auth-context";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="userId">{auth.userId}</span>
      <span data-testid="username">{auth.username}</span>
      <span data-testid="serverName">{auth.serverName}</span>
      <span data-testid="isAuth">{String(auth.isAuthenticated)}</span>
      <button onClick={auth.clearAuth}>clear</button>
    </div>
  );
}

describe("AuthContext", () => {
  it("provides auth data from props", () => {
    render(
      <AuthProvider userId="u1" username="alice" serverName="MyServer">
        <TestConsumer />
      </AuthProvider>,
    );
    expect(screen.getByTestId("userId")).toHaveTextContent("u1");
    expect(screen.getByTestId("username")).toHaveTextContent("alice");
    expect(screen.getByTestId("serverName")).toHaveTextContent(
      "MyServer",
    );
    expect(screen.getByTestId("isAuth")).toHaveTextContent("true");
  });

  it("clears auth on clearAuth()", async () => {
    render(
      <AuthProvider userId="u1" username="alice" serverName="MyServer">
        <TestConsumer />
      </AuthProvider>,
    );
    await act(async () => {
      screen.getByText("clear").click();
    });
    expect(screen.getByTestId("isAuth")).toHaveTextContent("false");
  });

  it("throws when used outside provider", () => {
    // Suppress React error boundary console output
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow();
    spy.mockRestore();
  });
});
