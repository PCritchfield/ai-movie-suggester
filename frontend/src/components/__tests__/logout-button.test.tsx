import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

const mockApiPost = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiPost: (...args: unknown[]) => mockApiPost(...args),
}));

import { AuthProvider } from "@/lib/auth/auth-context";
import { LogoutButton } from "../logout-button";
import { ApiAuthError } from "@/lib/api/types";

function renderWithAuth(ui: React.ReactElement) {
  return render(
    <AuthProvider userId="u1" username="alice" serverName="MyServer">
      {ui}
    </AuthProvider>
  );
}

describe("LogoutButton", () => {
  afterEach(() => {
    cleanup();
    mockPush.mockClear();
    mockApiPost.mockClear();
    vi.restoreAllMocks();
  });

  it("renders with Sign out text", () => {
    renderWithAuth(<LogoutButton />);
    expect(
      screen.getByRole("button", { name: /sign out/i })
    ).toBeInTheDocument();
  });

  it("calls apiPost /api/auth/logout on click", async () => {
    mockApiPost.mockResolvedValue({ detail: "Logged out" });
    const user = userEvent.setup();
    renderWithAuth(<LogoutButton />);
    await user.click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/api/auth/logout");
    });
  });

  it("redirects to /login on success", async () => {
    mockApiPost.mockResolvedValue({ detail: "Logged out" });
    const user = userEvent.setup();
    renderWithAuth(<LogoutButton />);
    await user.click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/login");
    });
  });

  it("redirects to /login?reason=session_expired on auth error", async () => {
    mockApiPost.mockRejectedValue(new ApiAuthError(401, {}));
    const user = userEvent.setup();
    renderWithAuth(<LogoutButton />);
    await user.click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/login?reason=session_expired");
    });
  });

  it("redirects to /login?reason=session_expired on network error", async () => {
    mockApiPost.mockRejectedValue(new TypeError("fetch failed"));
    const user = userEvent.setup();
    renderWithAuth(<LogoutButton />);
    await user.click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/login?reason=session_expired");
    });
  });

  it("disables button and shows Signing out... during request", async () => {
    let resolveLogout: (value: unknown) => void;
    mockApiPost.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveLogout = resolve;
        })
    );
    const user = userEvent.setup();
    renderWithAuth(<LogoutButton />);
    await user.click(screen.getByRole("button", { name: /sign out/i }));

    const signingOut = await screen.findByText(/signing out\.\.\./i);
    expect(signingOut).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeDisabled();

    resolveLogout!({ detail: "Logged out" });
  });

  it("has aria-live polite announcement during request", async () => {
    let resolveLogout: (value: unknown) => void;
    mockApiPost.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveLogout = resolve;
        })
    );
    const user = userEvent.setup();
    renderWithAuth(<LogoutButton />);
    await user.click(screen.getByRole("button", { name: /sign out/i }));

    await waitFor(() => {
      const liveRegion = document.querySelector("[aria-live='polite']");
      expect(liveRegion?.textContent).toContain("Signing out, please wait");
    });

    resolveLogout!({ detail: "Logged out" });
  });
});
