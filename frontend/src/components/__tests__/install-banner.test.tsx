import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { InstallBanner } from "../install-banner";
import * as hookModule from "@/hooks/use-install-prompt";

// Mock the hook so we can control its return value per test
vi.mock("@/hooks/use-install-prompt");

function mockHook(overrides: Partial<hookModule.UseInstallPromptReturn> = {}) {
  const defaults: hookModule.UseInstallPromptReturn = {
    canPrompt: true,
    platform: "android",
    prompt: vi.fn(),
    dismiss: vi.fn(),
  };
  vi.mocked(hookModule.useInstallPrompt).mockReturnValue({
    ...defaults,
    ...overrides,
  });
  return { ...defaults, ...overrides };
}

describe("InstallBanner", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders install button on Android", () => {
    mockHook({ platform: "android", canPrompt: true });
    render(<InstallBanner />);

    expect(screen.getByText("Install")).toBeInTheDocument();
    expect(
      screen.getByText(/Install AI Movie Suggester/)
    ).toBeInTheDocument();
  });

  it("renders iOS instructions on iOS Safari", () => {
    mockHook({ platform: "ios", canPrompt: true });
    render(<InstallBanner />);

    expect(
      screen.getByText(/Add to Home Screen/)
    ).toBeInTheDocument();
    // Should not show "Install" button on iOS — only the dismiss X
    expect(
      screen.queryByRole("button", { name: "Install" })
    ).not.toBeInTheDocument();
  });

  it("calls prompt() on Android install tap", async () => {
    const user = userEvent.setup();
    const hook = mockHook({ platform: "android", canPrompt: true });
    render(<InstallBanner />);

    await user.click(screen.getByRole("button", { name: "Install" }));
    expect(hook.prompt).toHaveBeenCalledOnce();
  });

  it("calls dismiss() and hides on dismiss tap", async () => {
    const user = userEvent.setup();
    const hook = mockHook({ platform: "android", canPrompt: true });
    render(<InstallBanner />);

    await user.click(
      screen.getByRole("button", { name: "Dismiss install banner" })
    );
    expect(hook.dismiss).toHaveBeenCalledOnce();
  });

  it("does not render when already dismissed", () => {
    mockHook({ canPrompt: false });
    const { container } = render(<InstallBanner />);

    expect(container.innerHTML).toBe("");
  });

  it("does not render when already installed", () => {
    mockHook({ canPrompt: false, platform: "unsupported" });
    const { container } = render(<InstallBanner />);

    expect(container.innerHTML).toBe("");
  });
});
