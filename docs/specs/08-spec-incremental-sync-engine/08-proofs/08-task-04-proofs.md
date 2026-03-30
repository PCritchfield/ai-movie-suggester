# Task 4.0 Proof — Admin Authorization + API Endpoints

## Subtasks Completed

| # | Subtask | Status |
|---|---------|--------|
| 4.1 | SyncTriggerResponse model | Done |
| 4.2 | SyncStatusResponse model | Done |
| 4.3 | SyncProgressResponse + SyncLastRunResponse models | Done |
| 4.4 | UserPolicy model with is_administrator field | Done |
| 4.5 | require_admin dependency | Done |
| 4.6 | POST /api/admin/sync/ endpoint (202/409/503) | Done |
| 4.7 | Config validation before background task creation | Done |
| 4.8 | GET /api/admin/sync/status endpoint | Done |
| 4.9 | Status returns running progress or last run | Done |
| 4.10-4.19 | Tests for admin dependency, trigger, and status | Done |

## Files Changed

- `backend/app/jellyfin/models.py` — Added `UserPolicy` model, added `policy` field to `UserInfo`
- `backend/app/sync/models.py` — Added Pydantic response models: `SyncTriggerResponse`, `SyncProgressResponse`, `SyncLastRunResponse`, `SyncStatusResponse`
- `backend/app/sync/dependencies.py` — New file: `require_admin` dependency
- `backend/app/sync/router.py` — New file: admin sync router with POST and GET endpoints
- `backend/tests/test_sync_router.py` — New file: 13 tests

## Verification

```
$ cd backend && uv run ruff check . && uv run ruff format --check .
All checks passed!
68 files already formatted

$ cd backend && uv run pytest --tb=short -q -m "not integration and not ollama_integration" tests/test_sync_router.py
13 passed

$ cd backend && uv run pyright --pythonversion 3.12
0 errors, 0 warnings, 0 informations
```

## Design Decisions

1. **Config validation before task creation**: The trigger endpoint calls `sync_engine.validate_config()` synchronously before creating the background task. This ensures SyncConfigError reaches the HTTP response as 503, rather than being silently swallowed inside the task.

2. **Lock check as fast-path**: The trigger endpoint checks `sync_engine.is_running` before creating the task. This is a fast-path rejection; the actual lock acquisition in `run_sync()` handles the TOCTOU window.

3. **require_admin fetches full session row**: The dependency retrieves the encrypted token from the session store to make a live Jellyfin API call checking `Policy.IsAdministrator`. This ensures admin status is always current, not cached.
