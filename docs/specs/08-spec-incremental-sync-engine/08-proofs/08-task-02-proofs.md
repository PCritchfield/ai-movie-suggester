# Task 2.0 Proof — LibraryStore Method Extensions

## Lint
```
$ cd backend && uv run ruff check . && uv run ruff format --check .
All checks passed!
64 files already formatted
```

## Tests
```
$ cd backend && uv run pytest --tb=short -q -m "not integration and not ollama_integration"
316 passed, 18 deselected
```

## New tests added (25 tests)
- get_all_ids: returns active IDs, excludes soft-deleted, empty store
- soft_delete_many: sets deleted_at, returns count, nonexistent IDs, empty list, >500 chunking
- hard_delete_many: removes rows, returns count, nonexistent IDs, empty list, >500 chunking
- get_tombstoned_ids: returns old deletions, excludes recent, empty
- enqueue_for_embedding: inserts pending, conflict resets status, empty list
- count_pending_embeddings: mixed statuses
- save_sync_run + get_last_sync_run: round-trip, returns most recent, returns None when empty
- get_all_hashes: excludes soft-deleted
- count: excludes soft-deleted (count_active removed — count() already filters active items)

## Sub-tasks completed
- [x] 2.1–2.6: Protocol extension with 8 new methods (count_active removed — count() covers this)
- [x] 2.7–2.15: Store implementations for all 8 methods
- [x] 2.16–2.31: Unit tests for all methods including chunking edge cases
