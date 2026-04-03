/**
 * Logout E2E test — uses the authenticatedPage fixture (storageState)
 * to start with a valid session, then exercises the logout flow.
 */

import { test, expect } from "../fixtures/auth.fixture";

test.describe("Logout", () => {
  test("should logout and redirect to login", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/");

    // Verify we're on the authenticated home page
    await expect(page.getByText(/Signed in as test-alice/)).toBeVisible();

    // Click sign out
    await page.getByRole("button", { name: "Sign out" }).click();

    // Should redirect to /login
    await page.waitForURL("/login");
    expect(page.url()).toContain("/login");

    // Verify session is truly invalidated — navigating to / should redirect
    // back to /login (server-side middleware check, not just client redirect)
    await page.goto("/");
    await page.waitForURL(/\/login/);
  });
});
