# 01-tasks-jellyfin-test-infrastructure

## Council Input

### Carrot (Coding) — TDD Guidance
- **Unit 1**: Partial TDD. Write a dummy test with `@pytest.mark.integration`, run `pytest --strict-markers` — it fails. Add marker registration — it passes. Config changes have no red phase, but marker enforcement does.
- **Unit 2**: Infrastructure — no application code. Treat Proof Artifacts as acceptance criteria. One exception: test unconditional teardown by running with a failing test and verifying no containers remain.
- **Unit 3**: Highest TDD value. Write `test_smoke.py` first (both tests). They fail. Implement fixture incrementally: polling loop → version check → wizard sequence → idempotency. Each step makes more tests pass.
- **Unit 4**: Pure YAML/config — no TDD cycle. Look up SHA pins before writing YAML. Treat Proof Artifacts as checklist.

### Magrat (Dev Environment) — Implementation Sequencing
- Each unit is its own commit. Do not bundle units.
- Verify `make test` passes with no integration tests collected before moving to Unit 2.
- Verify `make jellyfin-up` + `curl` works before writing any fixture code.
- Test idempotency (run twice without `jellyfin-down`) before calling Unit 3 done.
- `--add-host=host.docker.internal:host-gateway` should be unconditional in Makefile (harmless on Mac, required on Linux).
- `test-integration-full` needs proper shell block for unconditional teardown (Make runs each line in a separate shell).
- Only modify the pytest line in `make test`, not the npm test line.

## Relevant Files

### Existing files to modify
- `backend/pyproject.toml` — Add `markers` and `addopts = "--strict-markers"` to `[tool.pytest.ini_options]`
- `Makefile` — Update `test` target (pytest line only), add `jellyfin-up`, `jellyfin-down`, `test-integration`, `test-integration-full` targets
- `.github/workflows/ci.yml` — Add `-m "not integration"` to backend pytest invocation (lines 76-82)

### New files to create
- `backend/tests/integration/__init__.py` — Package marker for integration test directory
- `backend/tests/integration/conftest.py` — Session-scoped async fixture: Jellyfin polling, version check, wizard automation
- `backend/tests/integration/test_smoke.py` — Two smoke tests: `test_jellyfin_health`, `test_jellyfin_wizard_complete`
- `docker-compose.test.yml` — Jellyfin service for integration tests (pinned version, healthcheck, named volumes)
- `.github/workflows/integration.yml` — CI workflow: service container, warmer step, pytest, pass-through check
- `.github/dependabot.yml` — Docker-compose ecosystem monitoring for Jellyfin image

### Notes
- Unit tests live in `backend/tests/` (existing). Integration tests live in `backend/tests/integration/` (new).
- Use `uv run pytest` for running tests locally outside containers, `docker compose run --rm backend pytest` inside containers.
- Follow conventional commits: `feat:` for new infrastructure, `fix:` for corrections.
- All Python code must pass `ruff check`, `ruff format`, and `pyright`.

## Tasks

### [x] 1.0 pytest Marker Registration + Unit Test Isolation

Establish the `@pytest.mark.integration` marker and ensure `make test` and CI exclude integration tests. Pure configuration — no application code.

**TDD approach:** Write a dummy test with `@pytest.mark.integration` before registering the marker. Run `pytest --strict-markers` — it errors. Register the marker — it passes. Then verify `make test` and `ci.yml` exclude it.

#### 1.0 Proof Artifact(s)

- CLI: `make test` passes with no Jellyfin running, output shows 0 integration tests collected
- CLI: `uv run pytest --collect-only -m integration` inside dev container shows the integration test directory is recognized
- CLI: A test using `@pytest.mark.typo` errors under `--strict-markers` (then revert the typo)

#### 1.0 Tasks

- [x] 1.1 Create `backend/tests/integration/__init__.py` (empty file) and `backend/tests/integration/test_smoke.py` with a single placeholder test marked `@pytest.mark.integration` (e.g., `test_placeholder` that just passes). This is the TDD "red" setup.
- [x] 1.2 Run `uv run pytest --strict-markers` inside the dev container. Confirm it errors with "Unknown pytest.mark.integration". This is the red state.
- [x] 1.3 Add `markers` list and `addopts = "--strict-markers"` to `[tool.pytest.ini_options]` in `backend/pyproject.toml`. The marker entry: `"integration: marks tests as requiring a live Jellyfin instance (deselect with '-m \"not integration\"')"`.
- [x] 1.4 Run `uv run pytest --strict-markers --collect-only -m integration` inside the dev container. Confirm it collects the placeholder test without errors. This is the green state.
- [x] 1.5 Update the `make test` target in `Makefile`: add `-m "not integration"` to the pytest invocation line ONLY (do not modify the `npm test` line).
- [x] 1.6 Update the `ci.yml` backend job: add `-m "not integration"` to the `uv run pytest` invocation (the block around lines 76-82). Grep for `uv run pytest` to find the exact line.
- [x] 1.7 **Verify:** Run `make test` with no Jellyfin running. Confirm it passes, output shows 0 integration tests collected, and existing unit tests still run.
- [x] 1.8 **Verify:** Temporarily add `@pytest.mark.typo` to a unit test, run `make test`, confirm it errors. Revert the typo.

### [ ] 2.0 Jellyfin Docker Fixture + Makefile Targets

Provide a disposable Jellyfin container via `docker-compose.test.yml` and local DX targets. Infrastructure only — no Python code.

**TDD approach:** Infrastructure — treat Proof Artifacts as acceptance criteria. Work through targets in order: `jellyfin-up` → `jellyfin-down` → `test-integration` → `test-integration-full`. Verify each before moving to the next. Test unconditional teardown with a deliberately failing test.

#### 2.0 Proof Artifact(s)

- CLI: `make jellyfin-up` starts healthy Jellyfin, `docker compose -p ai-movie-suggester-test -f docker-compose.test.yml ps` shows `(healthy)`
- CLI: `curl http://localhost:8096/health` returns a response
- CLI: `make jellyfin-down` removes container and volumes
- CLI: `make test-integration-full` completes start-test-teardown cycle
- CLI: `make test-integration-full` with a failing test still runs `jellyfin-down` (no orphaned containers)

#### 2.0 Tasks

- [ ] 2.1 Create `docker-compose.test.yml` with Jellyfin service: image `jellyfin/jellyfin:10.10.7`, port `127.0.0.1:8096:8096`, healthcheck on `/health` with `start_period: 30s`, named volumes `jellyfin-test-config` and `jellyfin-test-cache`.
- [ ] 2.2 Add `jellyfin-up` target to `Makefile`: `docker compose -p ai-movie-suggester-test -f docker-compose.test.yml up -d jellyfin` followed by a poll loop or `docker compose wait` until healthy. Print "Jellyfin available at http://localhost:8096" on success.
- [ ] 2.3 Add `jellyfin-down` target to `Makefile`: `docker compose -p ai-movie-suggester-test -f docker-compose.test.yml down -v`. The `-v` is critical — removes named volumes for clean state.
- [ ] 2.4 **Verify:** Run `make jellyfin-up`, then `docker compose -p ai-movie-suggester-test -f docker-compose.test.yml ps` shows `(healthy)`. Run `curl http://localhost:8096/health`. Run `make jellyfin-down` and confirm volumes are gone.
- [ ] 2.5 Add `test-integration` target to `Makefile`: `docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm --add-host=host.docker.internal:host-gateway -e JELLYFIN_TEST_URL=http://host.docker.internal:8096 backend pytest -m integration -v`. The `--add-host` flag is unconditional (harmless on Mac, required on Linux).
- [ ] 2.6 Add `test-integration-full` target to `Makefile` with unconditional teardown. Use a shell block pattern so `jellyfin-down` runs even if tests fail. Example: `@$(MAKE) jellyfin-up && $(MAKE) test-integration; ret=$$?; $(MAKE) jellyfin-down; exit $$ret`. Test by temporarily making the placeholder test fail.
- [ ] 2.7 Update `.PHONY` line in `Makefile` to include all new targets: `jellyfin-up jellyfin-down test-integration test-integration-full`.
- [ ] 2.8 **Verify:** Run `make test-integration-full` — starts Jellyfin, runs placeholder integration test, tears down. Then make the placeholder test deliberately fail, run `make test-integration-full` again — confirm `jellyfin-down` still runs (no orphaned containers via `docker ps`).

### [ ] 3.0 First-Run Wizard Automation + Smoke Tests

Automate Jellyfin's first-run wizard and prove the fixture works with smoke tests. This is where TDD pays off most.

**TDD approach:** Write `test_smoke.py` with both tests FIRST (red). Then implement fixture incrementally:
1. Polling loop only → `test_jellyfin_health` passes (green)
2. Version check assertion → verify clear error on mismatch (red/green)
3. Wizard completion → `test_jellyfin_wizard_complete` passes (green)
4. Idempotency → run twice without `jellyfin-down`, both pass (green)

#### 3.0 Proof Artifact(s)

- CLI: `make test-integration` output shows `test_smoke.py::test_jellyfin_health PASSED` and `test_smoke.py::test_jellyfin_wizard_complete PASSED`
- CLI: Running `make test-integration` a second time (no `jellyfin-down`) still passes — idempotent
- CLI: Temporarily wrong version constant → fixture fails with clear version error message (then revert)

#### 3.0 Tasks

- [ ] 3.1 **RED:** Replace the placeholder test in `backend/tests/integration/test_smoke.py` with the two real smoke tests: `test_jellyfin_health` (async, asserts Jellyfin `/health` returns 200) and `test_jellyfin_wizard_complete` (async, asserts `/Startup/Configuration` returns 204 indicating wizard is complete, or `/System/Info/Public` returns valid server info). Both marked `@pytest.mark.integration`. Run `make jellyfin-up` then `make test-integration` — both tests fail (no fixture yet). This is the red state.
- [ ] 3.2 **GREEN (polling):** Create `backend/tests/integration/conftest.py` with a session-scoped async fixture using `@pytest_asyncio.fixture(scope="session")`. Define `JELLYFIN_TEST_URL` (from env, default `http://host.docker.internal:8096`), `EXPECTED_JELLYFIN_VERSION = "10.10.7"`, `TEST_ADMIN_USER = "admin"`, `TEST_ADMIN_PASS = "test-admin-password"` as module-level constants. Implement the polling loop: use `httpx.AsyncClient` to poll `JELLYFIN_TEST_URL/health` every 2 seconds with a 60-second timeout. Raise `TimeoutError` with a clear message if Jellyfin is not reachable. Run `make test-integration` — `test_jellyfin_health` should now pass.
- [ ] 3.3 **GREEN (version check):** Add version check to the fixture after polling succeeds. `GET /System/Info/Public` returns JSON with a `Version` field. Assert it matches `EXPECTED_JELLYFIN_VERSION`. If not, raise `AssertionError` with message: `f"Unexpected Jellyfin version {actual}, expected {expected}. Review wizard API compatibility."`. **Verify:** Temporarily set `EXPECTED_JELLYFIN_VERSION = "0.0.0"`, run `make test-integration`, confirm the clear error. Revert.
- [ ] 3.4 **GREEN (wizard):** Add wizard completion to the fixture. Check wizard state via `GET /Startup/Configuration` — if it returns 200, wizard needs completing. Complete via the 4-step API sequence: `POST /Startup/Configuration` (set preferred language/metadata), `POST /Startup/User` (create admin with `TEST_ADMIN_USER`/`TEST_ADMIN_PASS`), `POST /Startup/RemoteAccess` (enable remote access), `POST /Startup/Complete`. If wizard is already complete, skip silently (idempotent). Run `make test-integration` — both smoke tests should pass.
- [ ] 3.5 **GREEN (idempotency):** Run `make test-integration` a second time WITHOUT running `make jellyfin-down` first. Both tests must pass. The fixture must detect the wizard is already complete and skip it. If this fails, fix the wizard detection logic.
- [ ] 3.6 Ensure all helper fixtures/values the session-scoped fixture depends on are also session-scoped or plain constants (not function-scoped fixtures). Verify no `ScopeMismatch` errors.
- [ ] 3.7 Run `ruff check` and `pyright` on the new files. Fix any lint/type issues.
- [ ] 3.8 **Verify:** `make jellyfin-down` then `make test-integration-full` — clean start, both tests pass, teardown completes. Then `make jellyfin-up` + `make test-integration` twice — idempotent.

### [ ] 4.0 CI Workflow + Dependabot Configuration

Automate integration tests in GitHub Actions and configure Dependabot for Jellyfin image version monitoring.

**TDD approach:** Pure YAML/config — no TDD cycle. Look up SHA pins for non-GitHub-org actions before writing YAML. Treat Proof Artifacts as checklist. Verify manually with `gh workflow run` after merge.

#### 4.0 Proof Artifact(s)

- CLI: `gh workflow view integration.yml` shows workflow exists with correct triggers
- GitHub: Manual `gh workflow run integration.yml` triggers and completes successfully
- GitHub: The `integration-check` pass-through job correctly reports pass/fail
- CLI: `cat .github/dependabot.yml` shows docker-compose ecosystem entry for `docker-compose.test.yml`

#### 4.0 Tasks

- [ ] 4.1 Look up commit SHAs for all non-GitHub-org actions that the workflow will use (e.g., `astral-sh/setup-uv`, `dorny/paths-filter`). Record them before writing any YAML. GitHub-org actions (`actions/checkout`, `actions/setup-python`, `actions/cache`) may use version tags.
- [ ] 4.2 Create `.github/workflows/integration.yml` with triggers: `pull_request` on paths `backend/**` and `.github/workflows/integration.yml`, `push` to `main`, `schedule` weekly Monday 6am UTC, `workflow_dispatch`.
- [ ] 4.3 Define the Jellyfin service container in the integration job: image `jellyfin/jellyfin:10.10.7`, port `8096:8096`, health options `--health-cmd "curl -sf http://localhost:8096/health" --health-interval 10s --health-timeout 5s --health-retries 10`. The runner waits for healthy before starting steps.
- [ ] 4.4 Add a warmer step that polls `GET http://localhost:8096/System/Info/Public` until it returns 200 (with timeout). This is the secondary readiness gate — Jellyfin's `/health` can return 200 before the API is fully ready.
- [ ] 4.5 Add the test step: install uv, set up Python, restore uv cache (key: `uv-${{ runner.os }}-${{ hashFiles('backend/uv.lock') }}`), `uv sync --frozen --all-extras`, then `uv run pytest -m integration -v` with `JELLYFIN_TEST_URL=http://localhost:8096`. This runs directly on the runner, matching the `ci.yml` pattern.
- [ ] 4.6 Add the `integration-check` pass-through job following the same pattern as `backend-check` and `frontend-check` in `ci.yml`. It inspects `needs.integration.result` and exits 1 on failure. Do NOT use `continue-on-error: true` on the integration job — advisory status is controlled by not registering `integration-check` as a required branch protection check.
- [ ] 4.7 Create `.github/dependabot.yml` with a `docker-compose` ecosystem entry pointing at `docker-compose.test.yml`, weekly schedule. Add a comment noting that additional ecosystems (pip, npm) can be added in future PRs.
- [ ] 4.8 **Verify:** Push to a branch, confirm `integration.yml` triggers on PR. After merge, run `gh workflow run integration.yml` and watch it complete. Confirm the warmer step succeeds before pytest runs.
