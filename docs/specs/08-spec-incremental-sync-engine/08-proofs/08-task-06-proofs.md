# Task 6.0 Proof — Lifespan Wiring, Scheduled Sync, Health

## Subtasks Completed

| # | Subtask | Status |
|---|---------|--------|
| 6.1 | LibrarySyncStatus model | Done |
| 6.2 | Add library_sync field to HealthResponse | Done |
| 6.3 | Create SyncEngine in lifespan | Done |
| 6.4 | Store SyncEngine on app.state | Done |
| 6.5 | Mount sync router | Done |
| 6.6 | Periodic sync when config present | Done |
| 6.7 | Log when scheduled sync disabled | Done |
| 6.8 | Sync task uses sync-specific client | Done |
| 6.9 | Cancel sync task on shutdown | Done |
| 6.10 | Health endpoint library_sync section | Done |
| 6.11 | Graceful fallback when store unavailable | Done |
| 6.12-6.21 | Tests for lifespan wiring and health | Done |

## Files Changed

- `backend/app/models.py` — Added `LibrarySyncStatus` model, added `library_sync` field to `HealthResponse`
- `backend/app/main.py` — SyncEngine creation, sync router mount, periodic sync, shutdown cleanup, health update
- `backend/tests/test_health.py` — Added `test_health_includes_library_sync`
- `backend/tests/test_main.py` — Added `TestSyncEngineLifespan` class (3 tests)

## Verification

```
$ cd backend && uv run ruff check . && uv run ruff format --check .
All checks passed!
68 files already formatted

$ cd backend && uv run pytest --tb=short -q -m "not integration and not ollama_integration"
351 passed, 18 deselected

$ cd backend && uv run pyright --pythonversion 3.12
0 errors, 0 warnings, 0 informations
```

## Design Decisions

1. **SyncEngine always created**: The SyncEngine is created on every startup, even without API key configuration. This means admin endpoints can always check status (returning 503 on trigger if config missing) rather than crashing with a missing attribute error.

2. **Sync-specific JellyfinClient**: When `jellyfin_api_key` is configured, a separate JellyfinClient with `device_id="ai-movie-suggester-sync"` is used for the SyncEngine. This keeps sync traffic distinct in Jellyfin's session logs.

3. **Periodic sync sleeps first**: The `_periodic_sync` task calls `asyncio.sleep()` before the first sync. This prevents a sync run immediately on startup, which could compete with initial health checks and user requests.

4. **Health library_sync graceful fallback**: If the library store raises an exception during health check, `library_sync` is set to `None` rather than failing the entire health endpoint.
