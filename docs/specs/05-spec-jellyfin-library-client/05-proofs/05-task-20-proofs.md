# Task 2.0 Proof Artifacts — Library Metadata Store (SQLite Repository)

## Test Results

```
178 passed, 17 warnings in 0.73s
```

All unit tests pass (excluding integration tests). 23 new tests added for Task 2.0.

## Tests Added

### TestInit (schema and PRAGMAs)
- `test_table_exists` — library_items table exists in sqlite_master
- `test_indexes_exist` — idx_library_items_content_hash and idx_library_items_synced_at exist
- `test_wal_mode` — PRAGMA journal_mode returns 'wal'
- `test_foreign_keys_enabled` — PRAGMA foreign_keys returns 1
- `test_conn_before_init_raises` — _conn raises RuntimeError before init()

### TestUpsertMany (created/updated/unchanged tracking)
- `test_insert_new_items` — 3 new items -> UpsertResult(created=3, updated=0, unchanged=0)
- `test_reupsert_same_hash_unchanged` — same items same hash -> UpsertResult(created=0, updated=0, unchanged=3)
- `test_changed_hash_counts_as_updated` — one changed hash -> UpsertResult(created=0, updated=1, unchanged=2)
- `test_empty_list` — empty list -> UpsertResult(created=0, updated=0, unchanged=0)

### TestGet (single item)
- `test_round_trip_all_fields` — all fields round-trip correctly including JSON arrays
- `test_missing_id_returns_none` — non-existent ID returns None

### TestGetMany (batch)
- `test_fetch_subset` — 5 items, fetch 3, verify 3 returned
- `test_mix_existing_and_nonexistent` — mixed IDs, only existing returned
- `test_empty_list_returns_empty` — empty ID list returns empty list

### TestGetAllHashes
- `test_returns_hash_mapping` — maps jellyfin_id to content_hash for all items
- `test_empty_store_returns_empty_dict` — empty store returns {}

### TestCount
- `test_empty_store_returns_zero` — returns 0
- `test_after_inserts` — after 5 inserts returns 5

### TestContentHash
- `test_deterministic` — same input always produces same hash
- `test_different_input_different_hash` — different title produces different hash

### TestPeopleFiltering
- `test_only_actor_names_stored` — non-Actor entries excluded from stored people list

### TestValidation
- `test_malformed_item_skipped_valid_stored` — malformed item skipped with WARNING, valid items stored

### Config
- `test_library_db_path_default` — library_db_path defaults to "data/library.db"

## Files Created
- `backend/app/library/__init__.py` — empty module file
- `backend/app/library/models.py` — LibraryItemRow, UpsertResult, LibraryStoreProtocol
- `backend/app/library/store.py` — LibraryStore (SQLite repository)
- `backend/app/library/hashing.py` — placeholder hash with TODO comment

## Verification
- `library_db_path` in `backend/app/config.py`: defaults to `"data/library.db"`

## Lint / Format
- `ruff check app/ tests/` — All checks passed
- `ruff format --check app/ tests/` — All files formatted
