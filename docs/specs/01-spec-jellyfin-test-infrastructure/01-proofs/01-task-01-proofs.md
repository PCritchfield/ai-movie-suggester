# 01-task-01-proofs — pytest Marker Registration + Unit Test Isolation

## CLI Output: `make test` equivalent passes, 0 integration tests collected

```
$ uv run pytest -m "not integration" -v

============================= test session starts ==============================
platform darwin -- Python 3.12.10, pytest-9.0.2, pluggy-1.6.0
rootdir: .../backend
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
collecting ... collected 3 items / 1 deselected / 2 selected

tests/test_health.py::test_health_endpoint_returns_200 PASSED            [ 50%]
tests/test_health.py::test_health_endpoint_returns_status PASSED         [100%]

======================= 2 passed, 1 deselected in 0.01s ========================
```

**Result:** 2 unit tests pass, 1 integration test deselected. No Jellyfin required.

## CLI Output: `uv run pytest --collect-only -m integration` recognizes integration directory

```
$ uv run pytest --strict-markers --collect-only -m integration

============================= test session starts ==============================
platform darwin -- Python 3.12.10, pytest-9.0.2, pluggy-1.6.0
rootdir: .../backend
configfile: pyproject.toml
testpaths: tests
collected 3 items / 2 deselected / 1 selected

<Dir backend>
  <Package tests>
    <Package integration>
      <Module test_smoke.py>
        <Coroutine test_placeholder>

================= 1/3 tests collected (2 deselected) in 0.01s ==================
```

**Result:** 1 integration test collected from `tests/integration/test_smoke.py`.

## CLI Output: `@pytest.mark.typo` errors under `--strict-markers`

```
$ uv run pytest -m "not integration" -v  # with @pytest.mark.typo temporarily added

==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_health.py _____________________
'typo' not found in `markers` configuration option
=========================== short test summary info ============================
ERROR tests/test_health.py - Failed: 'typo' not found in `markers` configurat...
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
======================== 1 deselected, 1 error in 0.06s ========================
```

**Result:** Unregistered marker produces a collection error, not a warning.

**Note:** `strict_markers = true` config option was added alongside `addopts = "--strict-markers"` because pytest 9.x does not enforce strict markers via `addopts` alone. The config option provides reliable enforcement. The typo was reverted after verification.

## Verification

- [x] `make test` equivalent passes with no Jellyfin running
- [x] Integration test directory is recognized by pytest
- [x] Unregistered markers produce errors (not warnings)
- [x] `ruff check` and `ruff format --check` pass
