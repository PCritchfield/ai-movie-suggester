# Task 3.0 Proof Artifacts — Auth lifecycle E2E tests

## Files Created

### frontend/tests/e2e/auth/login.spec.ts

**Test 1: "should login with valid credentials and redirect to home"**
- Navigates to `/login`
- Fills `getByLabel("Username")` with "test-alice"
- Fills `getByLabel("Password")` with "test-alice-password"
- Clicks `getByRole("button", { name: "Sign in" })`
- Waits for URL to be "/"
- Asserts `getByText(/Signed in as test-alice/)` is visible (regex for split DOM nodes)

**Test 2: "should show error for invalid credentials"**
- Navigates to `/login`
- Fills credentials with wrong password
- Clicks sign in
- Asserts `getByRole("alert")` has text "Invalid username or password."
- Asserts URL still contains "/login" (no redirect)

### frontend/tests/e2e/auth/logout.spec.ts

**Test 3: "should logout and redirect to login"**
- Uses `authenticatedPage` fixture (storageState from globalSetup)
- Navigates to `/`, asserts "Signed in as test-alice" visible
- Clicks `getByRole("button", { name: "Sign out" })`
- Waits for redirect to `/login`
- Navigates to `/` again, asserts it redirects to `/login` (session truly invalidated)

### frontend/tests/e2e/auth/protected-routes.spec.ts

**Test 4: "should redirect unauthenticated user to login"**
- Creates fresh browser context (no storageState, no cookies)
- Navigates to `/`
- Asserts redirect to `/login` via middleware

**Test 5: "should show session expiry message when reason=session_expired"**
- Navigates to `/login?reason=session_expired`
- Asserts `getByRole("status")` has text "Your session has expired. Please sign in again."
- Asserts sign in button is visible

## Locator Strategy

All tests use accessible locators per spec:
- `page.getByLabel("Username")` / `page.getByLabel("Password")` for form inputs
- `page.getByRole("button", { name: "Sign in" })` / `page.getByRole("button", { name: "Sign out" })`
- `page.getByRole("alert")` for error messages
- `page.getByRole("status")` for session expiry message
- `page.getByText(/regex/)` for text assertions across split DOM nodes

No CSS selectors or test IDs used.

## Verification Notes

Tests cannot run in this worktree (no Docker stack). Verification commands:

```bash
# After npm ci && npx playwright install
npx playwright test tests/e2e/auth/ --project=chromium
npx playwright test tests/e2e/auth/ --project=chromium --project=firefox
npx playwright show-report
```

TypeScript correctness can be verified via `npx tsc --noEmit` once `@playwright/test` is installed.
