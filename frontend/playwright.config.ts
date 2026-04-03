import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E configuration.
 *
 * Coexists with Vitest — Playwright discovers *.spec.ts in tests/e2e/,
 * Vitest discovers *.test.ts elsewhere. No cross-discovery.
 *
 * Set PLAYWRIGHT_BASE_URL to target an already-running dev server.
 * Leave it unset and globalSetup will start Docker Compose automatically.
 *
 * Browser install (one-time):
 *   npx playwright install            # all browsers (local)
 *   npx playwright install chromium firefox  # CI subset
 */
export default defineConfig({
  testDir: "./tests/e2e",
  baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
  outputDir: "./test-results",

  reporter: [["html", { outputFolder: "./playwright-report" }]],

  globalSetup: "./tests/e2e/global-setup.ts",
  globalTeardown: "./tests/e2e/global-teardown.ts",

  use: {
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
  ],
});
