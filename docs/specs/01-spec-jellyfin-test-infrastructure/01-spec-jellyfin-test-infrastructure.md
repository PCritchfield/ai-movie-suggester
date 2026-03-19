# 01-spec-jellyfin-test-infrastructure

## Introduction/Overview

The ai-movie-suggester backend authenticates users against Jellyfin — making Jellyfin the identity provider for the entire application. Multiple upcoming Epic 1 issues (#28 Jellyfin client, #29 sessions, #30 auth middleware) require integration tests against a real Jellyfin instance. This spec defines the test infrastructure: a disposable Jellyfin Docker container, pytest integration markers, Makefile targets for local DX, and a separate CI workflow for automated integration testing.

## Goals

- Provide a reproducible, disposable Jellyfin instance for integration tests that starts clean every time
- Separate integration tests from unit tests so `make test` remains fast and requires no external services
- Enable developers to run integration tests locally with simple Makefile commands
- Add a CI workflow that runs integration tests on backend PRs, merges to main, weekly schedule, and manual dispatch
- Establish the pytest fixture and provisioning patterns that downstream auth issues (#28–#30) will build on

## User Stories

- **As a backend developer**, I want to run integration tests against a real Jellyfin instance so that I can verify auth flows work end-to-end without mocking.
- **As a contributor**, I want `make test` to stay fast and not require Jellyfin so that I can run unit tests during normal development without extra setup.
- **As a CI pipeline**, I want integration tests to run automatically on backend changes so that regressions in Jellyfin integration are caught before merge.
- **As a developer picking up an auth issue (#28–#30)**, I want a working Jellyfin fixture with provisioning helpers already in place so that I can write integration tests immediately.

## Demoable Units of Work

### Unit 1: pytest Marker Registration + Unit Test Isolation

**Purpose:** Establish the integration test marker and ensure both `make test` and CI exclude integration tests. This is the foundation that all other units depend on.

**Functional Requirements:**
- The `@pytest.mark.integration` marker shall be registered in `pyproject.toml` under `[tool.pytest.ini_options]` with a description
- `addopts = "--strict-markers"` shall be added to `[tool.pytest.ini_options]` in `pyproject.toml` so unregistered markers are errors (not warnings)
- **Existing file modification:** The `make test` target in `Makefile` shall be updated to pass `-m "not integration"` to the pytest invocation (currently runs all tests)
- **Existing file modification:** The `ci.yml` backend job pytest invocation (line 78) shall be updated to pass `-m "not integration"` so that integration tests are not collected in the fast CI pipeline
- The `backend/tests/integration/` directory shall exist with an `__init__.py` file
- Running `make test` with no Jellyfin instance available shall pass (no connection attempts)

**Proof Artifacts:**
- CLI: `make test` passes with no Jellyfin running, output shows no integration tests collected
- CLI: `uv run pytest --collect-only -m integration` inside the dev container shows the integration test directory is recognized
- CLI: Using an unregistered marker (e.g., `@pytest.mark.typo`) produces an error, not a warning

### Unit 2: Jellyfin Docker Fixture + Makefile Targets

**Purpose:** Provide a disposable Jellyfin container and local DX targets for starting, stopping, and running integration tests.

**Functional Requirements:**
- A `docker-compose.test.yml` file shall define a Jellyfin service pinned to `jellyfin/jellyfin:10.10.7`
- The Jellyfin service shall bind to `127.0.0.1:8096` only
- The Jellyfin service shall include a healthcheck that polls `/health` with `start_period: 30s`
- The Jellyfin service shall use named volumes (`jellyfin-test-config`, `jellyfin-test-cache`) for predictable state
- All test Makefile targets shall use `-p ai-movie-suggester-test` as the Compose project name, ensuring complete isolation from dev and production stacks
- The Makefile shall include the following targets:
  - `jellyfin-up`: start Jellyfin + wait for healthy (uses `docker compose -p ai-movie-suggester-test -f docker-compose.test.yml up -d jellyfin` and polls until healthy)
  - `jellyfin-down`: stop + explicitly remove volumes (`docker compose -p ai-movie-suggester-test -f docker-compose.test.yml down -v`)
  - `test-integration`: run integration tests in dev container with `-m integration` and `JELLYFIN_TEST_URL=http://host.docker.internal:8096`
  - `test-integration-full`: start Jellyfin, run tests, teardown — `jellyfin-down` shall run unconditionally even if tests fail (use shell `||` or `trap` pattern, not bare Make recipe chaining)
- The `test-integration` target shall pass `--add-host=host.docker.internal:host-gateway` for Linux compatibility
- Note: `make clean` does not cover test volumes — `jellyfin-down` is the correct cleanup for the test stack. This is by design (separate Compose project).

**Proof Artifacts:**
- CLI: `make jellyfin-up` starts a healthy Jellyfin container, `docker compose -p ai-movie-suggester-test -f docker-compose.test.yml ps` shows `(healthy)`
- CLI: `curl http://localhost:8096/health` returns a response
- CLI: `make jellyfin-down` removes the container and volumes
- CLI: `make test-integration-full` completes the full start-test-teardown cycle
- CLI: `make test-integration-full` with a failing test still runs `jellyfin-down` (teardown is unconditional)

### Unit 3: First-Run Wizard Automation + Smoke Tests

**Purpose:** Automate Jellyfin's first-run setup wizard and prove the fixture works with smoke tests.

**Functional Requirements:**
- A session-scoped async pytest fixture in `backend/tests/integration/conftest.py` shall detect whether Jellyfin's setup wizard needs to be completed
- The fixture shall use `@pytest_asyncio.fixture(scope="session")` (not `@pytest.fixture`) — session-scoped async fixtures require the `pytest_asyncio` decorator explicitly
- Any helper fixtures the session-scoped fixture depends on (e.g., `jellyfin_url`) must also be session-scoped or be plain constants, not function-scoped fixtures
- The fixture shall use `httpx.AsyncClient` for all Jellyfin API calls
- The fixture shall complete the wizard programmatically via Jellyfin's startup API (`/Startup/Configuration`, `/Startup/User`, `/Startup/RemoteAccess`, `/Startup/Complete`)
- The fixture shall use hardcoded test credentials (`TEST_ADMIN_USER = "admin"`, `TEST_ADMIN_PASS = "test-admin-password"`) that are clearly named as test constants
- The test constants shall never be imported outside the `backend/tests/integration/` directory
- The fixture shall read `JELLYFIN_TEST_URL` from the environment, defaulting to `http://host.docker.internal:8096` (the correct address when running inside a Docker container; developers running pytest directly on the host should set `JELLYFIN_TEST_URL=http://localhost:8096`)
- The fixture shall poll Jellyfin for readiness with a configurable timeout (default 60s) before attempting wizard completion
- The fixture shall check the Jellyfin version via `GET /System/Info/Public` and assert it matches the expected version (`10.10.7`). If the version does not match, the fixture shall fail with a clear message: "Unexpected Jellyfin version {actual}, expected {expected}. Review wizard API compatibility." This protects against silent breakage when Dependabot bumps the version.
- The fixture shall handle the case where the wizard is already completed (idempotent — no error on re-run)
- Smoke tests shall live in `backend/tests/integration/test_smoke.py`:
  - `test_jellyfin_health` — verify Jellyfin is reachable and returns a healthy status
  - `test_jellyfin_wizard_complete` — verify the first-run wizard has been completed successfully (or was already complete)
- Both smoke tests shall be async (consistent with the async fixture)

**Proof Artifacts:**
- CLI: `make test-integration` passes, output shows `test_smoke.py::test_jellyfin_health PASSED` and `test_smoke.py::test_jellyfin_wizard_complete PASSED`
- CLI: Running `make test-integration` a second time (wizard already completed) still passes — idempotent
- CLI: If Jellyfin version mismatches, fixture fails with a clear version error message

### Unit 4: CI Workflow + Dependabot Configuration

**Purpose:** Automate integration tests in GitHub Actions and keep the Jellyfin version current via Dependabot.

**Depends on:** Unit 1 (marker registration and `--strict-markers` must be in place, otherwise unregistered markers in other test files would cause errors).

**Functional Requirements:**
- A `.github/workflows/integration.yml` workflow shall run integration tests with the following triggers:
  - PR on paths: `backend/**`, `.github/workflows/integration.yml`
  - Push to `main` (always, regardless of paths)
  - Weekly schedule: Monday 6am UTC (`cron: '0 6 * * 1'`)
  - Manual `workflow_dispatch`
- The workflow shall define a Jellyfin service container pinned to `jellyfin/jellyfin:10.10.7` with a healthcheck via the `options` field:
  ```
  --health-cmd "curl -sf http://localhost:8096/health"
  --health-interval 10s
  --health-timeout 5s
  --health-retries 10
  ```
  The GitHub Actions runner will wait for the service container to be healthy before starting job steps.
- The workflow shall include an explicit warmer step that verifies `GET /System/Info/Public` returns 200, as a secondary gate — Jellyfin's `/health` can return 200 before the full API is ready
- The workflow shall run pytest directly on the runner using `uv run pytest -m integration -v` (matching the existing `ci.yml` pattern of running on the bare runner, not inside a Docker container). `JELLYFIN_TEST_URL` shall be set to `http://localhost:8096` (the service container is on localhost in CI).
- The integration job shall NOT use `continue-on-error: true`. Advisory status shall be achieved via branch protection settings (do not register `integration-check` as a required check). This ensures the pass-through job accurately reflects real failures.
- The workflow shall include a pass-through `integration-check` job (same pattern as `backend-check` and `frontend-check`) that inspects `needs.integration.result` — ready for future promotion to a required check
- The workflow shall cache `~/.cache/uv` with key `uv-${{ runner.os }}-${{ hashFiles('backend/uv.lock') }}` and restore-keys `uv-${{ runner.os }}-` (same pattern as `ci.yml`)
- All non-GitHub-org actions shall be pinned to commit SHAs. GitHub-org actions (`actions/checkout`, `actions/setup-python`, `actions/cache`) may use version tags. (Per Angua's security guidance — prevents supply chain attacks via compromised action tags.)
- A `.github/dependabot.yml` file shall be created with a `docker-compose` ecosystem entry pointing at `docker-compose.test.yml` with a weekly schedule. Note: this will monitor all images in that file (currently only Jellyfin). The file should include a comment noting that additional ecosystems (pip, npm) can be added in future PRs.

**Proof Artifacts:**
- CLI: `gh workflow view integration.yml` shows the workflow exists with correct triggers
- GitHub: A PR touching `backend/**` triggers the integration workflow
- GitHub: The integration job completes (pass or fail) without blocking PR merge (not a required check)
- GitHub: The `integration-check` pass-through job correctly reports pass/fail

## Non-Goals (Out of Scope)

1. **Test user creation and auth testing** — User provisioning, authentication, and token lifecycle tests belong to #28 (Jellyfin client) and #29 (sessions). This spec only provides the fixture and wizard automation they'll build on.
2. **Test media library seeding** — Populating Jellyfin with test movies/shows is an Epic 2 concern. The fixture starts with an empty library.
3. **Required CI status check** — The integration workflow is advisory-only in this spec. Promoting to required is a future decision after the fixture proves reliable.
4. **Frontend integration tests** — This spec covers backend pytest integration tests only. Frontend E2E tests (#31) are a separate concern.
5. **Production Jellyfin connectivity** — This is a test-only fixture. No changes to how the app connects to a real Jellyfin instance.
6. **Unified CI/local execution model** — CI runs pytest directly on the runner (`uv run pytest`); local runs pytest inside the dev container (`docker compose run`). This mirrors the existing pattern in `ci.yml` vs `make test`. The same markers and tests run in both environments.

## Design Considerations

No specific design requirements identified. This is backend infrastructure — no UI involved.

## Repository Standards

- **Python**: Type hints on all function signatures. Use `async/await` for I/O operations. Pydantic models for structured data. Lint with ruff.
- **Testing**: pytest with async support (`pytest-asyncio`). Session-scoped async fixtures use `@pytest_asyncio.fixture(scope="session")`. TDD: red-green-refactor.
- **Docker**: Follow the existing multi-file Compose pattern (base + overlay). Pin versions. Bind to `127.0.0.1`. Use Compose project names for stack isolation.
- **CI**: Follow the existing path-filtering + pass-through check pattern from `ci.yml`. Pin non-GitHub-org actions to commit SHAs. GitHub-org actions may use version tags.
- **Makefile**: Follow existing target naming and Compose invocation patterns.
- **Commits**: Conventional commits (`feat:`, `fix:`, `chore:`, etc.).

## Technical Considerations

- **Jellyfin first-run wizard**: Jellyfin 10.9+ requires completing a multi-step startup wizard via API before user management is available. The fixture must detect and handle this. The API sequence is: `POST /Startup/Configuration` → `POST /Startup/User` → `POST /Startup/RemoteAccess` → `POST /Startup/Complete`. This is the highest-risk part of the implementation — Jellyfin may change this API between versions. A version-check assertion in the fixture mitigates this by failing fast with a clear message.
- **`host.docker.internal` networking**: The dev container needs to reach Jellyfin running on the Docker host. This works automatically on Docker Desktop (Mac/Windows). On Linux, `--add-host=host.docker.internal:host-gateway` must be passed to `docker compose run`. The Makefile must handle this. In CI, pytest runs directly on the runner, so Jellyfin is on `localhost:8096` — no `host.docker.internal` needed.
- **`JELLYFIN_TEST_URL` default**: The fixture defaults to `http://host.docker.internal:8096` because it is designed to run inside a Docker container (via `make test-integration`). Developers running pytest directly on the host, or CI, should set `JELLYFIN_TEST_URL=http://localhost:8096`. This is an intentional divergence from `localhost` as the default, because `localhost` inside a container refers to the container itself, not the host.
- **Volume state between runs**: If `jellyfin-down` is not run between test sessions, the next run starts with previous state (wizard already completed, possibly leftover users). All fixtures must be idempotent — handle pre-existing state gracefully. `jellyfin-down` runs `docker compose down -v` to remove volumes.
- **Compose project isolation**: Test targets use `-p ai-movie-suggester-test` to avoid collisions with dev/prod stacks. `make clean` does not affect test volumes — use `make jellyfin-down` for test cleanup.
- **Startup timing**: Jellyfin's `/health` endpoint may return 200 before the full API is ready. The CI workflow uses a healthcheck on the service container (waits for `/health`) plus a warmer step against `/System/Info/Public`. The pytest fixture uses a polling loop with timeout.
- **httpx dependency**: The project already has `httpx` in backend dependencies. The integration fixtures will use `httpx.AsyncClient` for Jellyfin API calls.
- **Async fixture scope**: `asyncio_mode = "auto"` is already configured in `pyproject.toml`. Session-scoped async fixtures require `@pytest_asyncio.fixture(scope="session")` — the standard `@pytest.fixture` decorator does not support async session scope correctly. `pytest-asyncio>=0.24.0` is already in dev dependencies.

## Security Considerations

- **Test credentials are hardcoded** — `TEST_ADMIN_USER` and `TEST_ADMIN_PASS` live in `conftest.py` as clearly-named constants. Approved by Angua (Security) because the target is a disposable localhost container with no real data. Conditions: obviously synthetic values, `127.0.0.1` binding only, never imported outside test directory.
- **No real Jellyfin connection** — The test fixture is completely isolated from any production or personal Jellyfin instance.
- **No secrets in CI** — The integration workflow uses the same hardcoded test credentials. No GitHub Actions secrets needed for this spec.
- **Pinned Jellyfin image** — Supply chain risk mitigated by pinning to a specific version tag. Dependabot provides automated version bump PRs for review.
- **SHA-pinned CI actions** — All non-GitHub-org actions in `integration.yml` must be pinned to commit SHAs to prevent supply chain attacks via compromised action tags.
- **Compose project isolation** — Test stack uses a separate Compose project name to prevent accidental interaction with dev/prod containers.

## Success Metrics

1. **`make test` runs in <15 seconds** with no Jellyfin dependency (no regression from adding integration infrastructure)
2. **`make test-integration-full` completes in <90 seconds** including Jellyfin startup, wizard completion, smoke tests, and teardown
3. **CI integration workflow completes in <5 minutes** end-to-end
4. **Zero flaky runs** in the first 10 CI executions (the trust-earning period before considering required status)
5. **Downstream issues (#28–#30) can add integration tests** by importing the fixture and adding `@pytest.mark.integration` — no additional infrastructure setup needed

## Open Questions

No open questions. All questions resolved during council review:
- **Jellyfin version in `.env.example`?** No — Dependabot reads the Compose file, not env vars. Keep version in `docker-compose.test.yml` only.
- **Version-check assertion?** Yes — added to Unit 3 as a functional requirement. Fails fast with clear message on version mismatch.
