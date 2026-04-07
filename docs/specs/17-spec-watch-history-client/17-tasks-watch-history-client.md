# 17 Tasks - Watch History Client

## Relevant Files

### Files to Create
- `backend/tests/test_watch_history.py` — Unit tests for `WatchHistoryEntry`, `get_watched_items`, `get_favorite_items`

### Files to Modify
- `backend/app/jellyfin/models.py` — Add `WatchHistoryEntry` frozen dataclass
- `backend/app/jellyfin/client.py` — Add `_parse_watch_entry`, `get_watched_items`, `get_favorite_items` methods to `JellyfinClient`
- `backend/tests/integration/test_jellyfin_client.py` — Add integration tests for both new methods

### Files to Reference (read-only)
- `backend/app/jellyfin/errors.py` — `JellyfinAuthError`, `JellyfinConnectionError`, `JellyfinError`
- `backend/app/permissions/service.py` — `_CacheEntry` dataclass pattern, `_fetch_permitted_ids` pagination pattern
- `backend/tests/test_jellyfin_client.py` — `mock_http`, `jf_client`, `_FAKE_REQUEST` fixtures and test patterns
- `backend/tests/integration/conftest.py` — `JellyfinInstance`, `jellyfin`, `test_users`, `TEST_USER_ALICE`, `TEST_USER_ALICE_PASS` fixtures

## Tasks

### [x] 1.0 WatchHistoryEntry Model + get_watched_items with Unit Tests

Add the `WatchHistoryEntry` frozen dataclass to `models.py` and the `get_watched_items` method (with `_parse_watch_entry` static parser) to `client.py`. Write the full unit test suite for both the model and the method in `test_watch_history.py`.

**Scope:** FR-1.1 through FR-1.7 from Demoable Unit 1, plus FR-3.1 through FR-3.6 unit tests for `get_watched_items` and model tests from Demoable Unit 3.

**Why tests are bundled here:** The spec is TDD-friendly — the proof artifacts for Unit 1 are all unit tests. Writing model + method + tests together produces a single demoable increment: "the watched-items path works end-to-end in unit tests."

#### 1.0 Proof Artifact(s)
- `make test` passes: `WatchHistoryEntry` is frozen/immutable, fields have correct types
- `make test` passes: `get_watched_items` sends correct URL, query params (`IsPlayed=true`, `IncludeItemTypes=Movie`, `SortBy=DatePlayed`, `SortOrder=Descending`, `Recursive=true`), no `Fields` param
- `make test` passes: `get_watched_items` parses mock Jellyfin JSON into `list[WatchHistoryEntry]` with correct field values including `last_played_date` as `datetime`
- `make test` passes: `get_watched_items` auto-paginates (two-page mock: 200 + 50 items, all 250 returned)
- `make test` passes: empty watch history returns `[]`; missing/empty `UserData` yields safe defaults (`last_played_date=None`, `play_count=0`, `is_favorite=False`)
- `make test` passes: error paths — 401 raises `JellyfinAuthError`, transport error raises `JellyfinConnectionError`, 500 raises `JellyfinError`
- `make lint` passes with all new code

#### 1.0 Tasks

##### Model (FR-1.1)
- [x] 1.1 Add `WatchHistoryEntry` frozen dataclass to `models.py` with fields: `jellyfin_id: str`, `last_played_date: datetime | None`, `play_count: int`, `is_favorite: bool`. Use `@dataclass(frozen=True, slots=True)`. Add the `datetime` import at the top of the file. (file: `backend/app/jellyfin/models.py`)
- [x] 1.2 Add import of `WatchHistoryEntry` to the `from app.jellyfin.models import ...` line in `client.py`. (file: `backend/app/jellyfin/client.py`)

##### Parser (FR-1.5)
- [x] 1.3 Add `_parse_watch_entry` static method to `JellyfinClient` that extracts `jellyfin_id` from `item["Id"]`, `last_played_date` from `item["UserData"]["LastPlayedDate"]` (parsed via `datetime.fromisoformat()`, `None` if absent/null), `play_count` from `item["UserData"]["PlayCount"]` (default `0`), and `is_favorite` from `item["UserData"]["IsFavorite"]` (default `False`). Handle missing `UserData` key and empty `UserData` dict gracefully. Add `from datetime import datetime` import. (file: `backend/app/jellyfin/client.py`)

##### Method (FR-1.2 through FR-1.4, FR-1.6, FR-1.7)
- [x] 1.4 Add `get_watched_items(self, token: str, user_id: str) -> list[WatchHistoryEntry]` method to `JellyfinClient`. Build params dict with `IsPlayed=true`, `IncludeItemTypes=Movie`, `SortBy=DatePlayed`, `SortOrder=Descending`, `Recursive=true`, `StartIndex`, and `Limit=200`. Do NOT include a `Fields` parameter. (file: `backend/app/jellyfin/client.py`)
- [x] 1.5 Implement auto-pagination loop inside `get_watched_items`: start at `StartIndex=0`, call `_request("GET", f"/Users/{user_id}/Items", token=token, params=params)`, parse response via `_parse_response` with a lambda that extracts `Items` list and `TotalRecordCount`, map each item through `_parse_watch_entry`, increment `StartIndex` by items received, stop when `StartIndex >= TotalRecordCount` or page is empty. Collect all entries into a single `list[WatchHistoryEntry]`. (file: `backend/app/jellyfin/client.py`)
- [x] 1.6 Add DEBUG logging inside the pagination loop: `logger.debug("watched_items_fetch page=%d items=%d", page_number, len(items))`. Never log token, user_id paired with item data, or any PII. (file: `backend/app/jellyfin/client.py`)

##### Unit Tests — Model
- [x] 1.7 Create `backend/tests/test_watch_history.py` with imports: `WatchHistoryEntry` from `models`, `JellyfinClient` from `client`, `JellyfinAuthError`/`JellyfinConnectionError`/`JellyfinError` from `errors`, `AsyncMock` from `unittest.mock`, `httpx`, `pytest`. Add `mock_http` and `jf_client` fixtures matching the pattern in `test_jellyfin_client.py`. Add `_FAKE_REQUEST = httpx.Request("GET", "http://fake")`. (file: `backend/tests/test_watch_history.py`)
- [x] 1.8 Add test `test_watch_history_entry_is_frozen` — create a `WatchHistoryEntry`, assert assigning to `jellyfin_id` raises `dataclasses.FrozenInstanceError`. (file: `backend/tests/test_watch_history.py`)
- [x] 1.9 Add test `test_watch_history_entry_fields_and_types` — create a `WatchHistoryEntry` with all fields populated (including a real `datetime` for `last_played_date`), assert each field value and type. Verify `last_played_date=None` is accepted. (file: `backend/tests/test_watch_history.py`)

##### Unit Tests — get_watched_items Success Path
- [x] 1.10 Add test `test_get_watched_items_sends_correct_request` — mock `mock_http.request` to return a 200 response with `{"Items": [], "TotalRecordCount": 0}`. Call `get_watched_items("tok-123", "uid-1")`. Inspect `mock_http.request.call_args`: assert method is `GET`, URL contains `/Users/uid-1/Items`, params include `IsPlayed=true`, `IncludeItemTypes=Movie`, `SortBy=DatePlayed`, `SortOrder=Descending`, `Recursive=true`. Assert `Fields` is NOT in params. Assert `Token=tok-123` is in the Authorization header. (file: `backend/tests/test_watch_history.py`)
- [x] 1.11 Add test `test_get_watched_items_parses_response` — mock response with 2 items including realistic `UserData` objects (one with `LastPlayedDate: "2025-12-15T20:30:00.0000000Z"`, `PlayCount: 3`, `IsFavorite: true`; one with `LastPlayedDate: "2025-11-01T10:00:00.0000000Z"`, `PlayCount: 1`, `IsFavorite: false`). Assert returned list has 2 `WatchHistoryEntry` objects with correct field values. Assert `last_played_date` is a `datetime` instance. (file: `backend/tests/test_watch_history.py`)

##### Unit Tests — Pagination
- [x] 1.12 Add test `test_get_watched_items_paginates_two_pages` — mock `mock_http.request` with `side_effect` returning two sequential responses: page 1 with 200 items and `TotalRecordCount=250`, page 2 with 50 items and `TotalRecordCount=250`. Assert returned list has 250 entries. Assert `mock_http.request.call_count == 2`. Assert second call's params have `StartIndex=200`. (file: `backend/tests/test_watch_history.py`)

##### Unit Tests — Empty / Edge Cases
- [x] 1.13 Add test `test_get_watched_items_empty_history` — mock response with `{"Items": [], "TotalRecordCount": 0}`. Assert returns empty list `[]`. (file: `backend/tests/test_watch_history.py`)
- [x] 1.14 Add test `test_get_watched_items_missing_user_data` — mock response with an item that has no `UserData` key at all. Assert the parsed entry has `last_played_date=None`, `play_count=0`, `is_favorite=False`. (file: `backend/tests/test_watch_history.py`)
- [x] 1.15 Add test `test_get_watched_items_empty_user_data` — mock response with an item where `UserData` is `{}`. Assert same safe defaults as 1.14. (file: `backend/tests/test_watch_history.py`)
- [x] 1.16 Add test `test_get_watched_items_null_last_played_date` — mock response with `UserData` present but `LastPlayedDate` is `null`. Assert `last_played_date=None`. (file: `backend/tests/test_watch_history.py`)

##### Unit Tests — Error Paths
- [x] 1.17 Add test `test_get_watched_items_auth_error` — mock `mock_http.request` returning 401 response. Assert `get_watched_items` raises `JellyfinAuthError`. (file: `backend/tests/test_watch_history.py`)
- [x] 1.18 Add test `test_get_watched_items_connection_error` — mock `mock_http.request.side_effect = httpx.ConnectError("Connection refused")`. Assert raises `JellyfinConnectionError`. (file: `backend/tests/test_watch_history.py`)
- [x] 1.19 Add test `test_get_watched_items_unexpected_status` — mock `mock_http.request` returning 500 response. Assert raises `JellyfinError`. (file: `backend/tests/test_watch_history.py`)

##### Validation
- [x] 1.20 Run `make lint` — all new code in `models.py`, `client.py`, and `test_watch_history.py` passes ruff. (file: N/A)
- [x] 1.21 Run `make test` — all new unit tests pass. (file: N/A)

---

### [x] 2.0 get_favorite_items Method with Unit Tests

Add the `get_favorite_items` method to `client.py`, reusing `_parse_watch_entry` from Task 1.0. Write the full unit test suite for the method in the same `test_watch_history.py` file.

**Scope:** FR-2.1 through FR-2.6 from Demoable Unit 2, plus FR-3.1 through FR-3.6 unit tests for `get_favorite_items` from Demoable Unit 3.

**Why this is separate from 1.0:** Different query parameters (no `SortBy`/`SortOrder`, `IsFavorite=true` instead of `IsPlayed=true`) and independent proof artifacts. Keeps PRs reviewable and each task independently demoable.

#### 2.0 Proof Artifact(s)
- `make test` passes: `get_favorite_items` sends correct URL, query params (`IsFavorite=true`, `IncludeItemTypes=Movie`, `Recursive=true`), no `SortBy`/`SortOrder`, no `Fields` param
- `make test` passes: `get_favorite_items` parses mock response into `list[WatchHistoryEntry]` with correct field values
- `make test` passes: `get_favorite_items` auto-paginates (two-page mock, all entries returned)
- `make test` passes: empty favorites returns `[]`; unplayed favorite parsed correctly (`last_played_date=None`, `play_count=0`, `is_favorite=True`)
- `make test` passes: error paths — 401 raises `JellyfinAuthError`, transport error raises `JellyfinConnectionError`, 500 raises `JellyfinError`
- `make lint` passes with all new code

#### 2.0 Tasks

##### Method (FR-2.1 through FR-2.6)
- [x] 2.1 Add `get_favorite_items(self, token: str, user_id: str) -> list[WatchHistoryEntry]` method to `JellyfinClient`. Build params dict with `IsFavorite=true`, `IncludeItemTypes=Movie`, `Recursive=true`, `StartIndex`, and `Limit=200`. Do NOT include `SortBy`, `SortOrder`, or `Fields` parameters. (file: `backend/app/jellyfin/client.py`)
- [x] 2.2 Implement auto-pagination loop inside `get_favorite_items` using the same pattern as `get_watched_items` (1.5): call `_request`, parse via `_parse_response`, map items through `_parse_watch_entry`, increment `StartIndex`, stop when done. Reuse the same `_parse_watch_entry` static method from Task 1.3. (file: `backend/app/jellyfin/client.py`)
- [x] 2.3 Add DEBUG logging inside the pagination loop: `logger.debug("favorite_items_fetch page=%d items=%d", page_number, len(items))`. Same PII discipline as 1.6. (file: `backend/app/jellyfin/client.py`)

##### Unit Tests — get_favorite_items Success Path
- [x] 2.4 Add test `test_get_favorite_items_sends_correct_request` — mock `mock_http.request` to return a 200 response with `{"Items": [], "TotalRecordCount": 0}`. Call `get_favorite_items("tok-123", "uid-1")`. Inspect `mock_http.request.call_args`: assert method is `GET`, URL contains `/Users/uid-1/Items`, params include `IsFavorite=true`, `IncludeItemTypes=Movie`, `Recursive=true`. Assert `SortBy` is NOT in params. Assert `SortOrder` is NOT in params. Assert `Fields` is NOT in params. Assert `Token=tok-123` is in the Authorization header. (file: `backend/tests/test_watch_history.py`)
- [x] 2.5 Add test `test_get_favorite_items_parses_response` — mock response with 2 items including `UserData` with `IsFavorite: true`. Assert returned list has 2 `WatchHistoryEntry` objects with correct field values. (file: `backend/tests/test_watch_history.py`)

##### Unit Tests — Pagination
- [x] 2.6 Add test `test_get_favorite_items_paginates_two_pages` — mock `mock_http.request` with `side_effect` returning two sequential responses: page 1 with 200 items and `TotalRecordCount=250`, page 2 with 50 items and `TotalRecordCount=250`. Assert returned list has 250 entries. Assert `mock_http.request.call_count == 2`. (file: `backend/tests/test_watch_history.py`)

##### Unit Tests — Empty / Edge Cases
- [x] 2.7 Add test `test_get_favorite_items_empty_favorites` — mock response with `{"Items": [], "TotalRecordCount": 0}`. Assert returns empty list `[]`. (file: `backend/tests/test_watch_history.py`)
- [x] 2.8 Add test `test_get_favorite_items_unplayed_favorite` — mock response with one item where `UserData` has `IsFavorite: true`, `Played: false`, no `LastPlayedDate`, `PlayCount: 0`. Assert parsed entry has `is_favorite=True`, `last_played_date=None`, `play_count=0`. (file: `backend/tests/test_watch_history.py`)

##### Unit Tests — Error Paths
- [x] 2.9 Add test `test_get_favorite_items_auth_error` — mock `mock_http.request` returning 401 response. Assert `get_favorite_items` raises `JellyfinAuthError`. (file: `backend/tests/test_watch_history.py`)
- [x] 2.10 Add test `test_get_favorite_items_connection_error` — mock `mock_http.request.side_effect = httpx.ConnectError("Connection refused")`. Assert raises `JellyfinConnectionError`. (file: `backend/tests/test_watch_history.py`)
- [x] 2.11 Add test `test_get_favorite_items_unexpected_status` — mock `mock_http.request` returning 500 response. Assert raises `JellyfinError`. (file: `backend/tests/test_watch_history.py`)

##### Validation
- [x] 2.12 Run `make lint` — all new code passes ruff. (file: N/A)
- [x] 2.13 Run `make test` — all unit tests from Tasks 1.0 and 2.0 pass. (file: N/A)

---

### [x] 3.0 Integration Tests + Final Validation

Add integration tests in `backend/tests/integration/` that call both `get_watched_items` and `get_favorite_items` against the real disposable Jellyfin instance. Run full validation suite.

**Scope:** FR-3.7 through FR-3.9 from Demoable Unit 3 — the integration test and final lint/test gate.

**Why this is a separate task:** Integration tests require `make jellyfin-up` and exercise the real Jellyfin API shape (empty-list response from a test instance with no library content). This is a distinct verification step from the mock-based unit tests in Tasks 1.0 and 2.0.

#### 3.0 Proof Artifact(s)
- `make test-integration` passes: `get_watched_items` returns `list[WatchHistoryEntry]` (empty list) against real Jellyfin
- `make test-integration` passes: `get_favorite_items` returns `list[WatchHistoryEntry]` (empty list) against real Jellyfin
- `make test` passes: all unit tests from Tasks 1.0 and 2.0 still green
- `make lint` passes: all new modules clean

#### 3.0 Tasks

##### Integration Tests (FR-3.7)
- [x] 3.1 Add `WatchHistoryEntry` import to `backend/tests/integration/test_jellyfin_client.py`. (file: `backend/tests/integration/test_jellyfin_client.py`)
- [x] 3.2 Add integration test `test_get_watched_items_returns_list` — authenticate as `TEST_USER_ALICE` via `jf_client.authenticate()`, call `get_watched_items(auth.access_token, auth.user_id)`, assert return type is `list`, assert all elements (if any) are `WatchHistoryEntry` instances. The test Jellyfin has no library content, so an empty list is the expected result. Mark with `@pytest.mark.integration`. (file: `backend/tests/integration/test_jellyfin_client.py`)
- [x] 3.3 Add integration test `test_get_favorite_items_returns_list` — same pattern as 3.2 but calling `get_favorite_items`. Assert return type is `list`, assert all elements (if any) are `WatchHistoryEntry` instances. Mark with `@pytest.mark.integration`. (file: `backend/tests/integration/test_jellyfin_client.py`)

##### Final Validation (FR-3.8, FR-3.9)
- [x] 3.4 Run `make test` — all unit tests from Tasks 1.0 and 2.0 still green. (file: N/A)
- [x] 3.5 Run `make lint` — all new and modified modules pass ruff. (file: N/A)
- [ ] 3.6 Run `make test-integration` (requires `make jellyfin-up`) — both new integration tests pass. (file: N/A)
