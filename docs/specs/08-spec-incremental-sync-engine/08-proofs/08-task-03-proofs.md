# Task 3.0 Proof Artifacts — SyncEngine Core

## Test Results

```
tests/test_sync_engine.py::test_sync_basic_two_pages PASSED
tests/test_sync_engine.py::test_sync_unchanged_items PASSED
tests/test_sync_engine.py::test_sync_changed_item PASSED
tests/test_sync_engine.py::test_sync_deletion_detected PASSED
tests/test_sync_engine.py::test_sync_deletion_safety_threshold PASSED
tests/test_sync_engine.py::test_sync_per_item_failure PASSED
tests/test_sync_engine.py::test_sync_page_level_failure PASSED
tests/test_sync_engine.py::test_sync_concurrent_rejection PASSED
tests/test_sync_engine.py::test_sync_missing_api_key PASSED
tests/test_sync_engine.py::test_sync_missing_admin_user_id PASSED
tests/test_sync_engine.py::test_hash_determinism PASSED
tests/test_sync_engine.py::test_hash_different_input PASSED
tests/test_sync_engine.py::test_sync_wal_checkpoint PASSED
tests/test_sync_engine.py::test_sync_saves_sync_run PASSED

14 passed
```

## Sync Flow Verification

### Items classified correctly
- New items (no existing hash): `items_created` incremented, upserted + enqueued
- Changed items (hash mismatch): `items_updated` incremented, upserted + enqueued
- Unchanged items (hash match): `items_unchanged` incremented, NOT upserted/enqueued

### Deletion detection
- Items in store but not in Jellyfin response: detected as deleted
- 50% safety threshold: prevents mass tombstoning when Jellyfin returns partial data
- Threshold uses `max(last_sync_total, active_count)` as denominator

### Failure handling
- Per-item failure: logged, item skipped, `items_failed` incremented, sync continues
- Page-level failure: committed pages preserved, status set to 'failed' with error
- Missing config: `SyncConfigError` raised before any work starts
- Concurrent sync: `SyncAlreadyRunningError` raised immediately

### WAL checkpoint
- Triggered when WAL file exceeds configured threshold
- Uses PRAGMA wal_checkpoint(PASSIVE)

### Content hashing
- Uses `build_composite_text(item).text` as input (not `compute_content_hash()`)
- SHA-256 hex digest, deterministic

## Lint / Type Check

```
ruff check:    0 errors
ruff format:   0 reformats needed
pyright:       0 errors, 0 warnings
```
