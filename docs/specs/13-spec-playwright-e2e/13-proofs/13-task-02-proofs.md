# Task 2.0 Proof Artifacts — globalSetup/globalTeardown

## Files Created / Modified

### frontend/tests/e2e/global-setup.ts (replaced stub with full implementation)

**Key functions:**
- `startDockerCompose()` — writes `.env.e2e` to `.auth/`, runs `docker compose up -d` with project name `ai-movie-suggester-e2e`, writes sentinel file
- `waitForServices(baseUrl?)` — polls Jellyfin/backend/frontend with 2s interval, 120s timeout. If `PLAYWRIGHT_BASE_URL` set, only polls that URL
- `completeJellyfinWizard(jellyfinUrl)` — TypeScript port of `backend/tests/integration/conftest.py` wizard sequence. Returns admin token. Handles both fresh (empty password) and already-configured instances
- `provisionTestUsers(jellyfinUrl, adminToken)` — Creates test-alice and test-bob if not already present. Idempotent
- `createStorageState(baseUrl)` — Uses Playwright's `request.newContext()` API for programmatic login, saves cookies to `.auth/state.json`

**PLAYWRIGHT_BASE_URL behavior:**
- Set: logs "Using existing server at <url>", skips Compose, skips wizard/user provisioning, only creates storageState
- Unset: full lifecycle (Compose start, health poll, wizard, users, storageState)

### frontend/tests/e2e/global-teardown.ts (replaced stub with full implementation)

- Checks for sentinel file `.auth/.compose-started`
- If present: runs `docker compose down -v` to tear down services
- Deletes entire `.auth/` directory recursively

### frontend/tests/e2e/fixtures/auth.fixture.ts (created)

- Extends Playwright's base `test` with `authenticatedPage` fixture
- Loads `storageState` from `.auth/state.json`
- Creates a new browser context per test, yields page, closes context in cleanup
- Exports `test` and `expect` for convenience imports

## .env.e2e Contents (written by globalSetup)

```
SESSION_SECRET=e2e0a1b2c3d4e5f6a7b8c9d0e1f2a3b4
SESSION_SECURE_COOKIE=false
JELLYFIN_URL=http://jellyfin:8096
CORS_ORIGIN=http://localhost:3000
OLLAMA_HOST=http://localhost:11434
LOG_LEVEL=debug
```

No real secrets — all test-only throwaway values. SESSION_SECRET avoids blocklisted substrings.

## Jellyfin Wizard API Sequence (ported from Python)

1. `GET /Startup/Configuration` — 200 = wizard needed, 404 = already done
2. `GET /Startup/User` — discover admin name (default: "root")
3. `POST /Startup/Configuration` — locale settings
4. `POST /Startup/User` — set admin + password
5. `POST /Startup/RemoteAccess` — enable remote access
6. `POST /Startup/Complete` — finalize
7. `POST /Users/AuthenticateByName` — authenticate (retry 10x with 3s delay)
   - Tries password first, then empty password (fresh instance)
   - If empty password works, sets the expected password via `/Users/{id}/Password`

## Idempotency

- Wizard: skipped if `GET /Startup/Configuration` returns 404
- User provisioning: checks `GET /Users` before creating
- storageState: overwritten each run
- Compose teardown: only runs if sentinel file exists
