import { render } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SwRegister } from "../sw-register";

describe("SwRegister", () => {
  const registerMock = vi.fn().mockResolvedValue(undefined);
  const originalEnv = process.env.NODE_ENV;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("navigator", {
      ...navigator,
      serviceWorker: { register: registerMock },
    });
  });

  afterEach(() => {
    process.env.NODE_ENV = originalEnv;
    vi.unstubAllGlobals();
  });

  it("registers /sw.js in production", () => {
    process.env.NODE_ENV = "production";

    render(<SwRegister />);

    expect(registerMock).toHaveBeenCalledWith("/sw.js");
  });

  it("does not register in non-production", () => {
    // vitest defaults to NODE_ENV=test
    render(<SwRegister />);
    expect(registerMock).not.toHaveBeenCalled();
  });

  it("renders nothing", () => {
    const { container } = render(<SwRegister />);
    expect(container.innerHTML).toBe("");
  });
});
