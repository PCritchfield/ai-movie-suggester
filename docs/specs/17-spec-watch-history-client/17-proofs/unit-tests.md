# Spec 17 — Unit Test Proof Artifact

## Test Run: `uv run pytest tests/test_watch_history.py -v`

**Date:** 2026-04-06
**Result:** 20 passed in 0.03s

### Test Results

```
tests/test_watch_history.py::TestWatchHistoryEntry::test_watch_history_entry_is_frozen PASSED
tests/test_watch_history.py::TestWatchHistoryEntry::test_watch_history_entry_fields_and_types PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_sends_correct_request PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_parses_response PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_paginates_two_pages PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_empty_history PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_missing_user_data PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_empty_user_data PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_null_last_played_date PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_auth_error PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_connection_error PASSED
tests/test_watch_history.py::TestGetWatchedItems::test_get_watched_items_unexpected_status PASSED
tests/test_watch_history.py::TestGetFavoriteItems::test_get_favorite_items_sends_correct_request PASSED
tests/test_watch_history.py::TestGetFavoriteItems::test_get_favorite_items_parses_response PASSED
tests/test_watch_history.py::TestGetFavoriteItems::test_get_favorite_items_paginates_two_pages PASSED
tests/test_watch_history.py::TestGetFavoriteItems::test_get_favorite_items_empty_favorites PASSED
tests/test_watch_history.py::TestGetFavoriteItems::test_get_favorite_items_unplayed_favorite PASSED
tests/test_watch_history.py::TestGetFavoriteItems::test_get_favorite_items_auth_error PASSED
tests/test_watch_history.py::TestGetFavoriteItems::test_get_favorite_items_connection_error PASSED
tests/test_watch_history.py::TestGetFavoriteItems::test_get_favorite_items_unexpected_status PASSED
```

### Lint Check: `uv run ruff check app/ tests/`

**Result:** All checks passed!

### Coverage Map

| Spec Requirement | Test(s) | Status |
|---|---|---|
| FR-1.1: WatchHistoryEntry frozen dataclass | test_watch_history_entry_is_frozen, test_watch_history_entry_fields_and_types | PASS |
| FR-1.2: get_watched_items signature | test_get_watched_items_sends_correct_request | PASS |
| FR-1.3: Correct query params (IsPlayed, SortBy, etc.) | test_get_watched_items_sends_correct_request | PASS |
| FR-1.4: Auto-pagination | test_get_watched_items_paginates_two_pages | PASS |
| FR-1.5: _parse_watch_entry | test_get_watched_items_parses_response, missing/empty/null UserData tests | PASS |
| FR-1.6: Error contract | test_get_watched_items_auth_error, _connection_error, _unexpected_status | PASS |
| FR-1.7: DEBUG logging | Verified in implementation (no PII logged) | N/A |
| FR-2.1: get_favorite_items signature | test_get_favorite_items_sends_correct_request | PASS |
| FR-2.2: Correct query params (IsFavorite, no SortBy) | test_get_favorite_items_sends_correct_request | PASS |
| FR-2.3: Auto-pagination | test_get_favorite_items_paginates_two_pages | PASS |
| FR-2.4: Reuses _parse_watch_entry | test_get_favorite_items_parses_response, _unplayed_favorite | PASS |
| FR-2.5: Error contract | test_get_favorite_items_auth_error, _connection_error, _unexpected_status | PASS |
| FR-2.6: DEBUG logging | Verified in implementation (no PII logged) | N/A |
| No Fields param sent | Both _sends_correct_request tests assert "Fields" not in params | PASS |

### Integration Tests

Integration tests written in `backend/tests/integration/test_jellyfin_client.py`:
- `test_get_watched_items_returns_list` — authenticates as alice, verifies `list[WatchHistoryEntry]`
- `test_get_favorite_items_returns_list` — authenticates as alice, verifies `list[WatchHistoryEntry]`

**Note:** Integration tests require `make jellyfin-up` (disposable Jellyfin container). Not run in this session as no Jellyfin container was available.
