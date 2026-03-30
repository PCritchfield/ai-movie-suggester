# Task 5.0 Proof Artifacts — Tombstone Purge

## Test Results

```
tests/test_sync_engine.py::test_purge_expired_tombstones PASSED
tests/test_sync_engine.py::test_purge_no_expired_tombstones PASSED
tests/test_sync_engine.py::test_purge_respects_ttl PASSED
tests/test_sync_engine.py::test_purge_called_at_end_of_sync PASSED
tests/test_sync_engine.py::test_purge_without_vector_repo PASSED
tests/test_sync_engine.py::test_delete_from_embedding_queue PASSED

6 passed
```

## Deletion Order Verification

The Vimes-mandated deletion order is enforced by sequential awaits in `purge_tombstones()`:

1. `vector_repo.delete_many(ids)` — vectors first
2. `library_store.delete_from_embedding_queue(ids)` — queue entries second
3. `library_store.hard_delete_many(ids)` — library rows last

This order ensures:
- No orphan vectors pointing to deleted library items
- No orphan queue entries for items that no longer exist
- Library items (the "source of truth" rows) are deleted last

### Edge cases verified
- `vector_repo=None`: vector deletion step is skipped cleanly
- No expired tombstones: returns 0, no deletion calls made
- TTL cutoff: `get_tombstoned_ids` receives `now - (ttl_days * 86400)`
- Purge failure during `run_sync`: caught, logged, does not change sync result status

## delete_from_embedding_queue verification

Integration test with real SQLite database:
- Enqueue 3 items
- Delete 2 specific items
- Verify only 1 remains in the queue
- Returns count of deleted rows (2)

## Lint / Type Check

```
ruff check:    0 errors
ruff format:   0 reformats needed
pyright:       0 errors, 0 warnings
```
