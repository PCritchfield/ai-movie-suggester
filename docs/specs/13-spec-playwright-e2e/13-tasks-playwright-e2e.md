# 13 Tasks — Playwright E2E Test Framework

## Relevant Files

- `frontend/package.json` - Add `@playwright/test` devDependency and `test:e2e` / `test:e2e:ui` npm scripts (modify)
- `frontend/playwright.config.ts` - Playwright configuration: browser projects, testDir, baseURL, globalSetup/globalTeardown, output directories, screenshot/trace settings (create)
- `frontend/.gitignore` - Add `test-results/`, `playwright-report/`, `.auth/` entries (modify)
- `frontend/tests/e2e/global-setup.ts` - Docker Compose orchestration, health polling, Jellyfin wizard completion, test user provisioning, storageState creation (create)
- `frontend/tests/e2e/global-teardown.ts` - Docker Compose teardown, `.auth/` cleanup (create)
- `frontend/tests/e2e/fixtures/auth.fixture.ts` - Reusable `authenticatedPage` fixture that loads storageState from `.auth/state.json` (create)
- `frontend/tests/e2e/auth/login.spec.ts` - Happy path login and invalid credentials E2E tests (create)
- `frontend/tests/e2e/auth/logout.spec.ts` - Logout flow E2E test (create)
- `frontend/tests/e2e/auth/protected-routes.spec.ts` - Protected page redirect and session expiry message E2E tests (create)
- `.github/workflows/e2e.yml` - GitHub Actions workflow for E2E tests: Chromium + Firefox on PRs to main, artifact upload on failure (create)
- `frontend/src/components/login-form.tsx` - Reference for locator strategy: `Label htmlFor="username"`, `Label htmlFor="password"`, `Button` with text "Sign in", `role="alert"` error container, `role="status"` session expiry message (read-only reference)
- `frontend/src/components/auth-home.tsx` - Reference for assertion: "Signed in as " + `<span>{username}</span>` split across DOM nodes (read-only reference)
- `frontend/src/components/logout-button.tsx` - Reference for locator: `Button` with text "Sign out" (read-only reference)
- `frontend/src/app/login/page.tsx` - Reference for `searchParams.reason` handling that drives session expiry message (read-only reference)
- `backend/tests/integration/conftest.py` - Reference for Jellyfin wizard API sequence, auth header format, test credentials, and user provisioning logic to port to TypeScript (read-only reference)
- `docker-compose.yml` - Base compose file for backend + frontend services (read-only reference, consumed by globalSetup)
- `docker-compose.test.yml` - Jellyfin test service definition (read-only reference, consumed by globalSetup)
- `.github/workflows/ci.yml` - Reference for CI patterns: pinned action versions, Node setup from `.nvmrc`, npm caching (read-only reference)

## Tasks

### [x] 1.0 Playwright installation, config, and gitignore

Install `@playwright/test` as a dev dependency, create `playwright.config.ts` with three browser projects (chromium, firefox, webkit), configure `testDir`, `baseURL`, output directories, screenshot-on-failure, trace-on-retry, `globalSetup`/`globalTeardown` paths, and npm scripts. Update `frontend/.gitignore` to exclude `test-results/`, `playwright-report/`, and `.auth/`. Verify Playwright discovers the config and coexists with Vitest without interference.

#### 1.0 Proof Artifact(s)

- **CLI output**: `npx playwright test --list` runs without errors and shows configured browser projects (chromium, firefox, webkit)
- **file diff**: `frontend/package.json` includes `@playwright/test` in `devDependencies` and scripts `test:e2e` and `test:e2e:ui`
- **file content**: `frontend/.gitignore` includes `test-results/`, `playwright-report/`, and `.auth/`
- **CLI output**: `npm test` (Vitest) still runs only existing component tests with no Playwright cross-discovery

#### 1.0 Tasks

- [x] 1.1 Install Playwright and add npm scripts: Run `npm install -D @playwright/test` in `frontend/`. Add two scripts to `frontend/package.json` in the `"scripts"` block: `"test:e2e": "playwright test"` and `"test:e2e:ui": "playwright test --ui"`. These go alongside the existing `"test": "vitest run"` script. Do NOT modify the existing `"test"` script.

- [x] 1.2 Create `frontend/playwright.config.ts` with the following configuration: import `defineConfig` and `devices` from `@playwright/test`. Set `testDir: "./tests/e2e"`. Set `baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000"`. Set `outputDir: "./test-results"`. Configure `reporter: [["html", { outputFolder: "./playwright-report" }]]`. Set `use.screenshot: "only-on-failure"` and `use.trace: "on-first-retry"`. Set `globalSetup: "./tests/e2e/global-setup.ts"` and `globalTeardown: "./tests/e2e/global-teardown.ts"`. Define three projects: `{ name: "chromium", use: { ...devices["Desktop Chrome"] } }`, `{ name: "firefox", use: { ...devices["Desktop Firefox"] } }`, `{ name: "webkit", use: { ...devices["Desktop Safari"] } }`. The `testMatch` default (`**/*.spec.ts`) is correct — Playwright uses `*.spec.ts` while Vitest uses `*.test.ts`, preventing cross-discovery.

- [x] 1.3 Update `frontend/.gitignore` to add three new entries under the existing `# testing` section (which already has `/coverage`): add `/test-results/`, `/playwright-report/`, and `/.auth/` on separate lines. These match the `outputDir`, `reporter.outputFolder`, and storageState directory from `playwright.config.ts`.

- [x] 1.4 Create placeholder files so Playwright can discover the config without errors: create empty directories `frontend/tests/e2e/auth/` and `frontend/tests/e2e/fixtures/`. Create stub files `frontend/tests/e2e/global-setup.ts` (export default async function `globalSetup() {}`) and `frontend/tests/e2e/global-teardown.ts` (export default async function `globalTeardown() {}`) so that `npx playwright test --list` does not fail on missing globalSetup/globalTeardown imports.

- [x] 1.5 Verify coexistence: run `npm test` (Vitest) and confirm it still discovers only the existing `tests/page.test.tsx` component test — no Playwright `*.spec.ts` files are picked up. Then run `npx playwright test --list` and confirm it shows the configured browser projects (chromium, firefox, webkit) and discovers files only from `tests/e2e/`. If no spec files exist yet, it should list zero tests but exit cleanly with no config errors.

### [ ] 2.0 globalSetup/globalTeardown — Docker Compose orchestration, Jellyfin wizard, and storageState

Implement `global-setup.ts` and `global-teardown.ts`. globalSetup checks `PLAYWRIGHT_BASE_URL`: if set, skip Docker Compose and target the existing server; if unset, start the combined stack (`docker-compose.yml` + `docker-compose.test.yml`) with project name `ai-movie-suggester-e2e` and a generated `.env.e2e` file in `frontend/.auth/`. Poll health endpoints for Jellyfin, backend, and frontend readiness. Complete the Jellyfin first-run wizard (rewritten in TypeScript from `backend/tests/integration/conftest.py`) and provision test users (`test-alice`, `test-bob`). Perform a programmatic login via `POST /api/auth/login` and save `storageState` to `frontend/.auth/state.json`. globalTeardown tears down Compose services (if started) and deletes the `.auth/` temp files. Create the `auth.fixture.ts` that extends Playwright's base `test` with an `authenticatedPage` fixture loading storageState.

#### 2.0 Proof Artifact(s)

- **log output**: globalSetup prints "Using existing server at PLAYWRIGHT_BASE_URL" when env var is set, or "Starting Docker Compose stack..." followed by health check readiness when unset
- **file created**: `frontend/.auth/state.json` exists after globalSetup and is deleted after globalTeardown
- **file created**: `frontend/.auth/.env.e2e` is written with correct test environment variables (hardcoded `SESSION_SECRET`, `SESSION_SECURE_COOKIE=false`, `JELLYFIN_URL`, etc.) and deleted on teardown
- **idempotency**: Running globalSetup twice against an already-provisioned Jellyfin instance completes without errors (wizard and user creation are idempotent)

#### 2.0 Tasks

- [ ] 2.1 Implement Docker Compose orchestration in `frontend/tests/e2e/global-setup.ts`: Check `process.env.PLAYWRIGHT_BASE_URL` — if set, log `"Using existing server at <url>"` and skip Compose startup. If unset, write the E2E `.env` file to `frontend/.auth/.env.e2e` (create `frontend/.auth/` directory if it does not exist via `fs.mkdirSync` with `recursive: true`). The `.env` file contents must be: `SESSION_SECRET=e2e0a1b2c3d4e5f6a7b8c9d0e1f2a3b4`, `SESSION_SECURE_COOKIE=false`, `JELLYFIN_URL=http://jellyfin:8096`, `CORS_ORIGIN=http://localhost:3000`, `OLLAMA_HOST=http://localhost:11434`, `LOG_LEVEL=debug`. Then spawn `docker compose -p ai-movie-suggester-e2e -f docker-compose.yml -f docker-compose.test.yml --env-file frontend/.auth/.env.e2e up -d` using `child_process.execSync` from the project root directory (`path.resolve(__dirname, "../../..")`). Store a flag (e.g., write a sentinel file `frontend/.auth/.compose-started`) so `globalTeardown` knows whether to tear down Compose.

- [ ] 2.2 Implement health check polling in `global-setup.ts`: After Compose startup (or when targeting an existing server), poll three endpoints in a loop with 2-second intervals and a 120-second timeout: (1) Jellyfin at `http://localhost:8096/health` expecting HTTP 200, (2) backend at `http://localhost:8000/health` expecting HTTP 200, (3) frontend at `http://localhost:3000` expecting any HTTP 2xx response. Use Node's built-in `fetch` (available in Node 20). If any endpoint is not ready before timeout, throw an error with a descriptive message including which service failed. When targeting an existing server via `PLAYWRIGHT_BASE_URL`, only poll the base URL (skip Jellyfin and backend health checks — those are the developer's responsibility).

- [ ] 2.3 Implement the Jellyfin first-run wizard in TypeScript within `global-setup.ts` as a function `completeJellyfinWizard(jellyfinUrl: string): Promise<string>` that returns the admin auth token. Port the logic from `backend/tests/integration/conftest.py` lines 99-198 using this API sequence: (1) `GET /Startup/Configuration` — if 200, wizard is not yet complete, proceed; if 404, wizard already done, skip to step 7. (2) `GET /Startup/User` — read `.Name` for admin username (default `"root"`). (3) `POST /Startup/Configuration` with JSON `{"UICulture":"en-US","MetadataCountryCode":"US","PreferredMetadataLanguage":"en"}`. (4) `POST /Startup/User` with JSON `{"Name":"<admin>","Password":"test-admin-password"}`. (5) `POST /Startup/RemoteAccess` with JSON `{"EnableRemoteAccess":true,"EnableAutomaticPortMapping":false}`. (6) `POST /Startup/Complete`. (7) `POST /Users/AuthenticateByName` with JSON `{"Username":"<admin>","Pw":"test-admin-password"}` and `Authorization` header matching the format from conftest.py: `'MediaBrowser Client="ai-movie-suggester-e2e", DeviceId="e2e-setup", Device="playwright", Version="0.0.0"'`. Retry up to 10 times with 3-second delays (auth may not be immediately ready after wizard). If auth with password fails, try empty password `""` (fresh instance), authenticate, then set the password via `POST /Users/{userId}/Password`. Return the `AccessToken` from the successful auth response.

- [ ] 2.4 Implement test user provisioning in `global-setup.ts` as a function `provisionTestUsers(jellyfinUrl: string, adminToken: string): Promise<void>`. Port the logic from `backend/tests/integration/conftest.py` lines 204-236: (1) `GET /Users` with header `Authorization: MediaBrowser ..., Token=<adminToken>` to list existing users. (2) For each user in the list `[{name: "test-alice", password: "test-alice-password"}, {name: "test-bob", password: "test-bob-password"}]`, check if the username exists in the response. If it does, skip. If not, `POST /Users/New` with JSON `{"Name":"<name>","Password":"<password>"}` and the admin token header. This is idempotent — safe to run against an already-provisioned instance.

- [ ] 2.5 Implement storageState creation in `global-setup.ts`: After wizard and user provisioning, perform a programmatic login by sending `POST http://localhost:3000/api/auth/login` (or `${PLAYWRIGHT_BASE_URL}/api/auth/login`) with JSON `{"username":"test-alice","password":"test-alice-password"}` and `credentials: "include"` to capture the `Set-Cookie` response header. Extract the `session_id` cookie from the response. Write a storageState JSON file to `frontend/.auth/state.json` in the format Playwright expects: `{"cookies": [{"name": "session_id", "value": "<value>", "domain": "localhost", "path": "/", "httpOnly": true, "secure": false, "sameSite": "Lax"}], "origins": []}`. Alternatively, use Playwright's `request.newContext()` API from `@playwright/test` to perform the login and call `context.storageState({ path: "frontend/.auth/state.json" })` to save cookies automatically — this is the cleaner approach.

- [ ] 2.6 Implement `frontend/tests/e2e/global-teardown.ts`: Check for the sentinel file `frontend/.auth/.compose-started` — if it exists, run `docker compose -p ai-movie-suggester-e2e -f docker-compose.yml -f docker-compose.test.yml down -v` via `child_process.execSync` from the project root to tear down services and remove volumes. Then delete the entire `frontend/.auth/` directory recursively via `fs.rmSync(path, { recursive: true, force: true })` to clean up `state.json`, `.env.e2e`, and the sentinel file.

- [ ] 2.7 Create `frontend/tests/e2e/fixtures/auth.fixture.ts`: Import `test as base` from `@playwright/test`. Export a custom `test` object using `base.extend<{ authenticatedPage: Page }>({ ... })`. The `authenticatedPage` fixture should create a new browser context using `browser.newContext({ storageState: "frontend/.auth/state.json" })`, create a new page from that context, yield the page via the fixture's `use()` callback, and then close the context in cleanup. Also export `expect` from `@playwright/test` for convenience. This fixture lets any non-auth test use `authenticatedPage` instead of `page` and skip the login UI.

### [ ] 3.0 Auth lifecycle E2E tests

Implement five auth lifecycle tests in `frontend/tests/e2e/auth/` across three spec files (`login.spec.ts`, `logout.spec.ts`, `protected-routes.spec.ts`): happy path login (fill credentials, submit, assert redirect to `/` and "Signed in as test-alice"), invalid credentials (fill bad password, assert error "Invalid username or password." and no redirect), logout (start authenticated via storageState, click "Sign out", assert redirect to `/login`, assert revisiting `/` redirects again), protected page redirect (fresh context without cookies, navigate to `/`, assert redirect to `/login`), and session expiry message (navigate to `/login?reason=session_expired`, assert "Your session has expired. Please sign in again."). All tests use accessible locators (`getByRole`, `getByLabel`, `getByText`) per the spec's locator strategy.

#### 3.0 Proof Artifact(s)

- **test output**: `npx playwright test tests/e2e/auth/ --project=chromium` passes with all five tests green
- **test output**: `npx playwright test tests/e2e/auth/ --project=chromium --project=firefox` passes on both browsers
- **HTML report**: `npx playwright show-report` displays all five test names with pass status
- **failure artifact**: A deliberately broken test produces a screenshot in `frontend/test-results/` captured by Playwright's screenshot-on-failure config

#### 3.0 Tasks

- [ ] 3.1 Create `frontend/tests/e2e/auth/login.spec.ts` with the **happy path login** test: Import `test` and `expect` from `@playwright/test` (NOT from the auth fixture — this test exercises the login UI directly, no storageState). Write a test named `"should login with valid credentials and redirect to home"`. Navigate to `/login`. Fill in the username field using `page.getByLabel("Username")` with value `"test-alice"`. Fill in the password field using `page.getByLabel("Password")` with value `"test-alice-password"`. Click the submit button using `page.getByRole("button", { name: "Sign in" })`. Wait for navigation using `page.waitForURL("/")`. Assert the page displays the signed-in message using `expect(page.getByText(/Signed in as test-alice/)).toBeVisible()` — use a regex because the `AuthHome` component splits "Signed in as " and the username across two DOM nodes (`<p>` text + `<span>`).

- [ ] 3.2 Add the **invalid credentials** test to `frontend/tests/e2e/auth/login.spec.ts`: Write a test named `"should show error for invalid credentials"`. Navigate to `/login`. Fill `page.getByLabel("Username")` with `"test-alice"`. Fill `page.getByLabel("Password")` with `"wrong-password"`. Click `page.getByRole("button", { name: "Sign in" })`. Assert the error message using `expect(page.getByRole("alert")).toHaveText("Invalid username or password.")` — the error `<p>` in `LoginForm` has `role="alert"` and displays the string from `mapError` when status is 401. Assert the URL is still `/login` using `expect(page.url()).toContain("/login")` to confirm no redirect occurred.

- [ ] 3.3 Create `frontend/tests/e2e/auth/logout.spec.ts` with the **logout** test: Import `test` and `expect` from `../fixtures/auth.fixture` (uses the `authenticatedPage` fixture with storageState). Write a test named `"should logout and redirect to login"` that uses `authenticatedPage` (destructured from the fixture). Navigate to `/`. Assert the page is the authenticated home by checking `expect(page.getByText(/Signed in as test-alice/)).toBeVisible()`. Click the logout button using `page.getByRole("button", { name: "Sign out" })`. Wait for navigation using `page.waitForURL("/login")`. Assert the URL contains `/login`. Then verify the session is truly invalidated: navigate to `/` again and assert the page redirects back to `/login` using `page.waitForURL(/\/login/)` — this confirms the middleware rejects the invalidated session, not just a client-side redirect.

- [ ] 3.4 Create `frontend/tests/e2e/auth/protected-routes.spec.ts` with the **protected page redirect** test: Import `test` and `expect` from `@playwright/test` (NOT from the auth fixture — this test needs a fresh context with no cookies). Write a test named `"should redirect unauthenticated user to login"`. Use `browser.newContext()` (no storageState) to get a clean context, then `context.newPage()`. Navigate to `/`. Assert the browser redirects to `/login` using `page.waitForURL(/\/login/)`. Close the context in cleanup. This tests the Next.js middleware that checks for the `session_id` cookie.

- [ ] 3.5 Add the **session expiry message** test to `frontend/tests/e2e/auth/protected-routes.spec.ts`: Write a test named `"should show session expiry message when reason=session_expired"`. Navigate to `/login?reason=session_expired`. Assert the session expiry message is visible using `expect(page.getByRole("status")).toHaveText("Your session has expired. Please sign in again.")` — the `LoginForm` component renders a `<p role="status">` with this text when `reason === "session_expired"` (from the `searchParams` prop in `login/page.tsx`). Also assert the login form is still present using `expect(page.getByRole("button", { name: "Sign in" })).toBeVisible()`.

- [ ] 3.6 Verify all five tests pass: Run `npx playwright test tests/e2e/auth/ --project=chromium` and confirm all five tests (happy login, invalid credentials, logout, protected redirect, session expiry) pass. Then run `npx playwright test tests/e2e/auth/ --project=chromium --project=firefox` to verify cross-browser. Generate the HTML report with `npx playwright show-report` and visually confirm test names and pass status.

### [ ] 4.0 CI workflow for E2E tests

Create `.github/workflows/e2e.yml` as a separate workflow. Triggers: `pull_request` to `main` (excluding drafts) and `workflow_dispatch`. Uses `ubuntu-latest`, sets up Node from `frontend/.nvmrc`, caches Playwright browser binaries keyed on `package-lock.json` hash, caches Docker layers. Runs `npm ci` and `npx playwright install --with-deps chromium firefox`. Generates a throwaway `.env` with `SESSION_SECRET` from `openssl rand -hex 32` and `SESSION_SECURE_COOKIE=false`. Does NOT set `PLAYWRIGHT_BASE_URL` (globalSetup manages Compose). Runs `npx playwright test --project=chromium --project=firefox`. Uploads `test-results/` and `playwright-report/` as artifacts on failure (7-day retention). Excludes `.auth/` from uploaded artifacts. Uses pinned action versions matching `ci.yml` security pattern.

#### 4.0 Proof Artifact(s)

- **lint output**: `actionlint .github/workflows/e2e.yml` passes without errors
- **CI run**: A manual `workflow_dispatch` run completes with Chromium and Firefox passing
- **failure artifacts**: An intentionally broken test uploads screenshots and traces as downloadable GitHub Actions artifacts
- **security check**: `.auth/` directory contents (storageState) are confirmed absent from uploaded artifacts

#### 4.0 Tasks

- [ ] 4.1 Create `.github/workflows/e2e.yml` with workflow triggers and runner setup: Set `name: E2E`. Configure triggers: `pull_request` to `main` with `types: [opened, synchronize, reopened]` (this excludes drafts — draft PRs have type `ready_for_review` which is not listed), and `workflow_dispatch` for manual runs. Use `runs-on: ubuntu-latest`. Add a single job named `e2e`. Use `defaults.run.working-directory: frontend`. Add step to checkout code using `actions/checkout@v4` (matching `ci.yml` pattern). Add step to set up Node using `actions/setup-node@v4` with `node-version-file: frontend/.nvmrc` and `cache: npm` with `cache-dependency-path: frontend/package-lock.json` (matching `ci.yml` lines 99-104).

- [ ] 4.2 Add Playwright browser caching and installation steps to `e2e.yml`: After Node setup and `npm ci`, add a cache step using `actions/cache@v4` with `path: ~/.cache/ms-playwright` and `key: playwright-${{ runner.os }}-${{ hashFiles('frontend/package-lock.json') }}` with `restore-keys: playwright-${{ runner.os }}-`. After the cache step, run `npx playwright install --with-deps chromium firefox` — this installs only the two browsers needed for CI (not webkit) along with their OS-level dependencies (`--with-deps` installs `libnss3`, `libatk1.0`, etc. on Ubuntu).

- [ ] 4.3 Add Docker layer caching step to `e2e.yml`: Before the test run, add a step that pulls and caches Docker images. Use `actions/cache@v4` with `path: /tmp/.docker-cache` and `key: docker-e2e-${{ runner.os }}-${{ hashFiles('docker-compose.yml', 'docker-compose.test.yml', 'backend/Dockerfile', 'frontend/Dockerfile') }}` with `restore-keys: docker-e2e-${{ runner.os }}-`. Alternatively, use `docker compose pull` as a pre-step so that the Jellyfin image is cached. The `globalSetup` handles the actual Compose startup — this step only pre-warms the image cache.

- [ ] 4.4 Add the `.env` generation and test execution steps to `e2e.yml`: Add a step to generate the test `.env` file in the project root (NOT in `frontend/.auth/` — that is handled by `globalSetup`): `echo "SESSION_SECRET=$(openssl rand -hex 32)" > .env`, followed by appending `SESSION_SECURE_COOKIE=false`, `JELLYFIN_URL=http://jellyfin:8096`, `CORS_ORIGIN=http://localhost:3000`, `OLLAMA_HOST=http://localhost:11434`, `LOG_LEVEL=debug` using `echo "KEY=VALUE" >> .env`. Important: do NOT set `PLAYWRIGHT_BASE_URL` — leaving it unset causes `globalSetup` to start the Docker Compose stack. Add the test execution step: `npx playwright test --project=chromium --project=firefox`.

- [ ] 4.5 Add artifact upload on failure to `e2e.yml`: After the test step, add two `actions/upload-artifact@v4` steps that run `if: ${{ !cancelled() }}` (runs on both failure and success, skipped only if cancelled — alternatively use `if: failure()` for failure-only upload). First artifact: `name: playwright-report`, `path: frontend/playwright-report/`, `retention-days: 7`. Second artifact: `name: test-results`, `path: frontend/test-results/`, `retention-days: 7`. Add `if-no-files-found: ignore` so the step does not fail when all tests pass (no failure screenshots). Do NOT upload `frontend/.auth/` — the storageState file contains the session cookie. Add a step after tests to ensure Compose is cleaned up even on failure: `if: always()` step running `docker compose -p ai-movie-suggester-e2e down -v || true` (the `|| true` prevents cleanup failure from masking the real test failure).

- [ ] 4.6 Add draft PR exclusion to `e2e.yml`: The `pull_request` trigger with `types: [opened, synchronize, reopened]` implicitly excludes drafts, but add an explicit job-level condition for clarity: `if: github.event.pull_request.draft == false || github.event_name == 'workflow_dispatch'`. This ensures the workflow does not run on draft PRs but always runs on manual dispatch. Verify the complete workflow file passes `actionlint` (install via `brew install actionlint` locally, or add a linting step to CI).
