# Task 4.0 Proof Artifacts — CI workflow for E2E tests

## File Created

### .github/workflows/e2e.yml

**Triggers:**
- `pull_request` to `main` with types `[opened, synchronize, reopened]` (excludes drafts implicitly)
- `workflow_dispatch` for manual runs

**Job-level condition:**
- `if: github.event.pull_request.draft == false || github.event_name == 'workflow_dispatch'`

**Steps:**
1. `actions/checkout@v4` — matches ci.yml pattern
2. `actions/setup-node@v4` — Node from `frontend/.nvmrc`, npm cache from `package-lock.json`
3. `npm ci` — install dependencies
4. `actions/cache@v4` — cache `~/.cache/ms-playwright` keyed on `package-lock.json` hash
5. `npx playwright install --with-deps chromium firefox` — CI browsers only
6. `actions/cache@v4` — Docker layer cache
7. `docker compose pull` — pre-warm images (continue-on-error)
8. Generate `.env` — `SESSION_SECRET` from `openssl rand -hex 32`, test defaults
9. `npx playwright test --project=chromium --project=firefox` — run tests
10. `actions/upload-artifact@v4` — playwright-report (7-day retention, if: !cancelled())
11. `actions/upload-artifact@v4` — test-results (7-day retention, if: !cancelled())
12. Docker Compose cleanup (if: always(), || true to avoid masking failures)

**Security:**
- `.auth/` directory NOT uploaded as artifact (storageState contains session cookies)
- SESSION_SECRET generated at runtime via `openssl rand -hex 32` — no repository secrets needed
- Action versions match ci.yml pattern (v4 tags)
- PLAYWRIGHT_BASE_URL intentionally NOT set — globalSetup manages Compose lifecycle

**Draft PR exclusion:**
- `pull_request.types: [opened, synchronize, reopened]` omits `ready_for_review` (drafts)
- Explicit job-level `if` condition as belt-and-suspenders

## Verification Notes

```bash
# Validate workflow syntax (if actionlint is installed)
actionlint .github/workflows/e2e.yml

# Manual trigger after PR merge
gh workflow run e2e.yml
```

Workflow will be validated on first PR or manual dispatch. The `docker compose pull` step uses `continue-on-error: true` to avoid failures when images are already cached.
