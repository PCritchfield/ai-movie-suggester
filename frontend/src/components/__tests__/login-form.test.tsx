import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe, toHaveNoViolations } from "jest-axe";

expect.extend(toHaveNoViolations);

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Mock API client
const mockApiPost = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiPost: (...args: unknown[]) => mockApiPost(...args),
}));

import { LoginForm } from "../login-form";
import { ApiAuthError, ApiError } from "@/lib/api/types";

describe("LoginForm", () => {
  beforeEach(() => {
    mockPush.mockClear();
    mockApiPost.mockClear();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders a form with username and password inputs", () => {
    render(<LoginForm />);
    expect(screen.getByRole("form")).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("username has autocomplete=username and type=text", () => {
    render(<LoginForm />);
    const input = screen.getByLabelText(/username/i);
    expect(input).toHaveAttribute("autocomplete", "username");
    expect(input).toHaveAttribute("type", "text");
  });

  it("password has autocomplete=current-password and type=password", () => {
    render(<LoginForm />);
    const input = screen.getByLabelText(/password/i);
    expect(input).toHaveAttribute("autocomplete", "current-password");
    expect(input).toHaveAttribute("type", "password");
  });

  it("shows validation error on empty submit", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(
      screen.getByText(/username and password are required/i)
    ).toBeInTheDocument();
    expect(mockApiPost).not.toHaveBeenCalled();
  });

  it("redirects on successful login", async () => {
    mockApiPost.mockResolvedValue({
      user_id: "u1",
      username: "alice",
      server_name: "MyServer",
    });
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "pass123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/");
    });
  });

  it("shows error on 401", async () => {
    mockApiPost.mockRejectedValue(new ApiAuthError(401, {}));
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/invalid username or password/i)
      ).toBeInTheDocument();
    });
  });

  it("shows error on 403", async () => {
    mockApiPost.mockRejectedValue(new ApiAuthError(403, {}));
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "pass");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
    });
  });

  it("shows error on 502", async () => {
    mockApiPost.mockRejectedValue(new ApiError(502, {}));
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "pass");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/unable to reach the media server/i)
      ).toBeInTheDocument();
    });
  });

  it("shows error on 429", async () => {
    mockApiPost.mockRejectedValue(new ApiError(429, {}));
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "pass");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(screen.getByText(/too many login attempts/i)).toBeInTheDocument();
    });
  });

  it("shows error on network failure", async () => {
    mockApiPost.mockRejectedValue(new TypeError("Failed to fetch"));
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "pass");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/could not connect to the server/i)
      ).toBeInTheDocument();
    });
  });

  it("renders session_expired notice", () => {
    render(<LoginForm reason="session_expired" />);
    expect(screen.getByText(/your session has expired/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("does not render notice for unknown reason", () => {
    render(<LoginForm reason="unknown_value" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not render notice for undefined reason", () => {
    render(<LoginForm />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("disables button and shows Signing in... during request", async () => {
    let resolveLogin: (value: unknown) => void;
    mockApiPost.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveLogin = resolve;
        })
    );
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "pass");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    // Wait for the "Signing in..." text to appear
    const signingIn = await screen.findByText(/signing in\.\.\./i);
    expect(signingIn).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeDisabled();

    resolveLogin!({ user_id: "u1", username: "alice", server_name: "S" });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/");
    });
  });

  it("re-enables button after error", async () => {
    mockApiPost.mockRejectedValue(new ApiAuthError(401, {}));
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(screen.getByRole("button")).not.toBeDisabled();
    });
  });

  it("passes axe accessibility audit (default state)", async () => {
    const { container } = render(<LoginForm />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("passes axe accessibility audit (error state)", async () => {
    mockApiPost.mockRejectedValue(new ApiAuthError(401, {}));
    const user = userEvent.setup();
    const { container } = render(<LoginForm />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/invalid username or password/i)
      ).toBeInTheDocument();
    });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
