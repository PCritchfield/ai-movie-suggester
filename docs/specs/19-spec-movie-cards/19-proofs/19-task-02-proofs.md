# Task 2.0 — Extend Search Results (Rating + Runtime) — Proof Artifacts

## Test Results

```
101 passed, 1 deselected (Ollama integration — requires real instance)
```

### New Tests Added

- `test_sync_engine.py::test_sync_runtime_ticks_conversion` — 54000000000 ticks → 90 minutes
- `test_sync_engine.py::test_sync_runtime_ticks_none` — None → None
- `test_library_store.py::TestGet::test_runtime_minutes_round_trips` — 90 stores and retrieves
- `test_library_store.py::TestGet::test_runtime_minutes_null_round_trips` — None stores and retrieves
- `test_text_builder.py::test_runtime_included_when_present` — runtime appears in composite text
- `test_text_builder.py::test_runtime_omitted_when_none` — runtime omitted when None
- `test_search_service.py::TestSearchEnrichesWithMetadata` — community_rating and runtime_minutes on results

### Existing Tests Updated

- `test_search_service.py` — LibraryItemRow includes runtime_minutes=120
- `test_search_router.py` — LibraryItemRow includes runtime_minutes=120
- `test_library_store.py` — _make_item includes runtime_minutes=117

## Pipeline Verification

- Jellyfin → `RunTimeTicks` fetched via `_ITEM_FIELDS`
- Sync engine → `run_time_ticks // 600_000_000` → `runtime_minutes`
- LibraryStore → `runtime_minutes INTEGER` column (ALTERed if needed)
- Text builder → `Runtime: N minutes.` section, TEMPLATE_VERSION bumped to 3
- SearchResultItem → `community_rating` and `runtime_minutes` fields
- Frontend types → `community_rating: number | null`, `runtime_minutes: number | null`

## Template Version Warning

TEMPLATE_VERSION bumped from 2 → 3. First sync after deploy will re-queue all items for embedding.
