# Task 1.0 Proof Artifacts — Playwright installation, config, and gitignore

## Files Created / Modified

### frontend/package.json (modified)
- Added `@playwright/test` to `devDependencies`
- Added `"test:e2e": "playwright test"` script
- Added `"test:e2e:ui": "playwright test --ui"` script
- Existing `"test": "vitest run"` script unchanged

### frontend/playwright.config.ts (created)
- `testDir: "./tests/e2e"` — isolates Playwright from Vitest
- `baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000"`
- `outputDir: "./test-results"`, reporter to `./playwright-report`
- `screenshot: "only-on-failure"`, `trace: "on-first-retry"`
- `globalSetup` / `globalTeardown` paths configured
- Three projects: chromium, firefox, webkit

### frontend/.gitignore (modified)
- Added `/test-results/`, `/playwright-report/`, `/.auth/` under `# testing`

### frontend/vitest.config.ts (modified)
- Added `exclude: ["tests/e2e/**", "node_modules/**"]` to prevent Vitest from discovering Playwright spec files

### frontend/tests/e2e/global-setup.ts (created)
- Stub: `export default async function globalSetup(): Promise<void> {}`

### frontend/tests/e2e/global-teardown.ts (created)
- Stub: `export default async function globalTeardown(): Promise<void> {}`

### frontend/tests/e2e/auth/ (created, empty directory)
### frontend/tests/e2e/fixtures/ (created, empty directory)

## Vitest Coexistence

Vitest and Playwright coexist via:
1. Playwright uses `*.spec.ts` in `tests/e2e/`, Vitest uses `*.test.ts` elsewhere
2. Vitest config explicitly excludes `tests/e2e/**`
3. The `"test"` npm script (Vitest) is unchanged

## Verification Notes

Verification commands to run after `npm ci`:
```bash
# Install Playwright browsers (one-time)
npx playwright install

# Verify Playwright config is valid (should show 0 tests, 3 projects, no errors)
npx playwright test --list

# Verify Vitest still works (should run page.test.tsx only)
npm test
```

These cannot be run in this worktree session due to sandbox restrictions on npm, but the file structure and configuration are complete and correct.
