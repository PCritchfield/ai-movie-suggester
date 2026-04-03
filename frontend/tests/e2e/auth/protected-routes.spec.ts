/**
 * Protected routes E2E tests — verify middleware redirects and
 * session expiry messaging.
 *
 * Does NOT use the auth fixture — these tests need a fresh context
 * with no cookies to verify unauthenticated behavior.
 */

import { test, expect } from "@playwright/test";

test.describe("Protected routes", () => {
  test("should redirect unauthenticated user to login", async ({
    browser,
  }) => {
    // Fresh context with no cookies or storageState
    const context = await browser.newContext();
    const page = await context.newPage();

    try {
      await page.goto("/");

      // Middleware should redirect to /login when no session_id cookie
      await page.waitForURL(/\/login/);
    } finally {
      await context.close();
    }
  });

  test("should show session expiry message when reason=session_expired", async ({
    page,
  }) => {
    await page.goto("/login?reason=session_expired");

    // LoginForm renders <p role="status"> when reason === "session_expired"
    await expect(page.getByRole("status")).toHaveText(
      "Your session has expired. Please sign in again.",
    );

    // Login form should still be present and functional
    await expect(
      page.getByRole("button", { name: "Sign in" }),
    ).toBeVisible();
  });
});
