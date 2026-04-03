/**
 * Authenticated page fixture for E2E tests.
 *
 * Loads storageState from .auth/state.json (created by globalSetup)
 * so that tests start with a valid session cookie — no login UI needed.
 *
 * Usage in test files:
 *   import { test, expect } from "../fixtures/auth.fixture";
 *   test("my test", async ({ authenticatedPage }) => { ... });
 */

import { test as base, type Page } from "@playwright/test";
import path from "path";

const STORAGE_STATE_PATH = path.resolve(
  __dirname,
  "../../../.auth/state.json",
);

export const test = base.extend<{ authenticatedPage: Page }>({
  authenticatedPage: async ({ browser }, use) => {
    const context = await browser.newContext({
      storageState: STORAGE_STATE_PATH,
    });
    const page = await context.newPage();
    await use(page);
    await context.close();
  },
});

export { expect } from "@playwright/test";
