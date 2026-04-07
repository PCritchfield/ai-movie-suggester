# 17 Tasks - Watch History Client

## Tasks

### [ ] 1.0 WatchHistoryEntry Model + get_watched_items with Unit Tests

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
TBD

---

### [ ] 2.0 get_favorite_items Method with Unit Tests

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
TBD

---

### [ ] 3.0 Integration Tests + Final Validation

Add integration tests in `backend/tests/integration/` that call both `get_watched_items` and `get_favorite_items` against the real disposable Jellyfin instance. Run full validation suite.

**Scope:** FR-3.7 through FR-3.9 from Demoable Unit 3 — the integration test and final lint/test gate.

**Why this is a separate task:** Integration tests require `make jellyfin-up` and exercise the real Jellyfin API shape (empty-list response from a test instance with no library content). This is a distinct verification step from the mock-based unit tests in Tasks 1.0 and 2.0.

#### 3.0 Proof Artifact(s)
- `make test-integration` passes: `get_watched_items` returns `list[WatchHistoryEntry]` (empty list) against real Jellyfin
- `make test-integration` passes: `get_favorite_items` returns `list[WatchHistoryEntry]` (empty list) against real Jellyfin
- `make test` passes: all unit tests from Tasks 1.0 and 2.0 still green
- `make lint` passes: all new modules clean

#### 3.0 Tasks
TBD
