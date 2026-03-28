# Task 1.0 Proof — Configuration, Data Models, Schema Extensions

## Lint
```
$ cd backend && uv run ruff check . && uv run ruff format --check .
All checks passed!
64 files already formatted
```

## Tests
```
$ cd backend && uv run pytest --tb=short -q -m "not integration and not ollama_integration"
291 passed, 18 deselected
```

## Sub-tasks completed

- [x] 1.1–1.4: Config extensions (jellyfin_admin_user_id, sync_interval_hours, tombstone_ttl_days, wal_checkpoint_threshold_mb)
- [x] 1.5–1.9: Sync package with SyncResult, SyncRunRow, SyncState, SyncAlreadyRunningError, SyncConfigError
- [x] 1.10–1.11: Text builder re-export at app.library.text_builder
- [x] 1.12–1.16: Schema extensions (deleted_at column, embedding_queue table, sync_runs table, indexes, migration)
- [x] 1.17: .env.example updated with sync engine section
- [x] 1.18–1.22: Config tests (5 new tests)
- [x] 1.23–1.26: Schema tests (4 new tests)
- [x] 1.27–1.28: Model/import tests (2 new tests)
