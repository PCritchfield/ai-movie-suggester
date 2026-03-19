# 01-task-03-proofs — First-Run Wizard Automation + Smoke Tests

## CLI Output: Both smoke tests pass

```
$ make test-integration-full

Waiting for Jellyfin to become healthy...
Jellyfin available at http://localhost:8096
cd backend && JELLYFIN_TEST_URL=http://localhost:8096 uv run pytest -m integration -v

tests/integration/test_smoke.py::test_jellyfin_health PASSED             [ 50%]
tests/integration/test_smoke.py::test_jellyfin_wizard_complete PASSED    [100%]

======================= 2 passed, 2 deselected in 0.14s ========================
```

## CLI Output: Idempotent — second run without `jellyfin-down` still passes

```
$ make test-integration   # run 1: wizard completes
tests/integration/test_smoke.py::test_jellyfin_health PASSED             [ 50%]
tests/integration/test_smoke.py::test_jellyfin_wizard_complete PASSED    [100%]
======================= 2 passed, 2 deselected in 0.14s ========================

$ make test-integration   # run 2: wizard already complete, skipped
tests/integration/test_smoke.py::test_jellyfin_health PASSED             [ 50%]
tests/integration/test_smoke.py::test_jellyfin_wizard_complete PASSED    [100%]
======================= 2 passed, 2 deselected in 0.06s ========================
```

**Note:** After wizard completion, `GET /Startup/Configuration` returns 401 (not 200), so the `if resp.status_code == 200` guard skips the wizard steps. Idempotent by design.

## CLI Output: Version mismatch produces clear error

```
$ JELLYFIN_TEST_URL=http://localhost:8096 uv run pytest -m integration -v
  # with EXPECTED_JELLYFIN_VERSION = "0.0.0" temporarily

E  AssertionError: Unexpected Jellyfin version 10.10.7, expected 0.0.0.
   Review wizard API compatibility.
```

**Result:** Clear version error message when version doesn't match.

## Test Results

```
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
8 files already formatted

$ uv run pyright tests/integration/
0 errors, 0 warnings, 0 informations
```

## TDD Progression

1. **RED** (3.1): Both tests error — `fixture 'jellyfin_url' not found`
2. **GREEN polling** (3.2): `test_jellyfin_health` passes, `test_jellyfin_wizard_complete` fails (`StartupWizardCompleted` is `False`)
3. **GREEN version** (3.3): Version check passes with correct version, fails with clear message on mismatch
4. **GREEN wizard** (3.4): Both tests pass — wizard automated via 4-step API
5. **GREEN idempotency** (3.5): Second run passes without teardown

## Verification

- [x] Both smoke tests pass on clean start
- [x] Idempotent — second run without teardown passes
- [x] Version mismatch produces clear error message
- [x] No ScopeMismatch errors (all constants, no function-scoped fixtures)
- [x] `ruff check`, `ruff format`, and `pyright` pass
