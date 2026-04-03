/**
 * Login E2E tests — exercises the login form against a real Jellyfin backend.
 *
 * Does NOT use the auth fixture (no storageState) — these tests interact
 * with the login UI directly to verify the full authentication flow.
 */

import { test, expect } from "@playwright/test";

test.describe("Login", () => {
  test("should login with valid credentials and redirect to home", async ({
    page,
  }) => {
    await page.goto("/login");

    await page.getByLabel("Username").fill("test-alice");
    await page.getByLabel("Password").fill("test-alice-password");
    await page.getByRole("button", { name: "Sign in" }).click();

    await page.waitForURL("/");

    // AuthHome splits "Signed in as " and username across DOM nodes
    await expect(page.getByText(/Signed in as test-alice/)).toBeVisible();
  });

  test("should show error for invalid credentials", async ({ page }) => {
    await page.goto("/login");

    await page.getByLabel("Username").fill("test-alice");
    await page.getByLabel("Password").fill("wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByRole("alert")).toHaveText(
      "Invalid username or password.",
    );

    // Confirm no redirect occurred — still on /login
    expect(page.url()).toContain("/login");
  });
});
