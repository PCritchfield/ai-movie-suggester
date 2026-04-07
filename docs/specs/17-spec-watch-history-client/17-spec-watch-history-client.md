# 17-spec-watch-history-client

## Introduction/Overview

This spec adds two methods to the existing `JellyfinClient` for retrieving a user's watch history and favorite items. These are thin HTTP wrappers — consistent with the existing `get_items` and `get_all_items` patterns — that call Jellyfin's `/Users/{userId}/Items` endpoint with `IsPlayed=true` and `IsFavorite=true` filters respectively. The methods return a slim `WatchHistoryEntry` dataclass (not the full `LibraryItem`) containing only the user-scoped activity fields that the downstream history-aware ranking service (#119) needs: item ID, last played date, play count, and favorite status.

This is a backend-only spec. No API endpoints, no frontend changes, no new services. The methods are consumed internally by the ranking service in #119.

## Goals

- **Watched items retrieval**: Fetch all items a user has marked as played in Jellyfin, sorted by most recently played, returning only the activity metadata needed for ranking.
- **Favorite items retrieval**: Fetch all items a user has marked as favorite in Jellyfin, returning the same slim activity metadata.
- **Slim return type**: Return `WatchHistoryEntry` dataclasses with only the fields ranking needs (`jellyfin_id`, `last_played_date`, `play_count`, `is_favorite`), since full item metadata is already available in the local `library_items` table from sync.
- **Complete data**: Fetch ALL matching items with no hard cap, following the `PermissionService._fetch_permitted_ids` pattern. A limit would be a correctness bug for ranking — the ranker needs the full picture.
- **Consistent client patterns**: Reuse the existing `_request`, `_parse_response`, and `_headers` infrastructure in `JellyfinClient`. No new HTTP clients, no new service classes.

## User Stories

- **As the history-aware ranking service** (#119), I need the full list of a user's watched movies with temporal metadata (when played, how many times) so I can boost or penalize recommendations based on viewing history.
- **As the history-aware ranking service** (#119), I need the full list of a user's favorited movies so I can boost recommendations that are similar to the user's explicitly preferred content.
- **As a developer building #119**, I want watch history and favorites to come from dedicated `JellyfinClient` methods with a clean return type, so that the ranking service does not need to understand Jellyfin query parameters or parse raw API responses.

## Demoable Units of Work

### Unit 1: WatchHistoryEntry Model + get_watched_items Method

**Purpose:** Define the slim `WatchHistoryEntry` dataclass for user activity data and add a `get_watched_items` method to `JellyfinClient` that fetches all played items for a user, auto-paginating through the full result set.

**Functional Requirements:**

- FR-1.1: The system shall define a `WatchHistoryEntry` dataclass in `backend/app/jellyfin/models.py`:
  ```python
  @dataclass(frozen=True, slots=True)
  class WatchHistoryEntry:
      jellyfin_id: str
      last_played_date: datetime | None
      play_count: int
      is_favorite: bool
  ```
  This is a plain dataclass, not a Pydantic model. It does not extend `LibraryItem`. The separation is intentional: `LibraryItem` represents library-scoped catalog metadata (used for sync and embedding), while `WatchHistoryEntry` represents user-scoped activity data (used for ranking). These are different domains with different lifecycles and access patterns.

- FR-1.2: The system shall add a `get_watched_items` method to `JellyfinClient` in `backend/app/jellyfin/client.py` with this signature:
  ```python
  async def get_watched_items(
      self,
      token: str,
      user_id: str,
  ) -> list[WatchHistoryEntry]:
  ```
  The method accepts the user's Jellyfin token and user ID as parameters. The token is passed through to `_request` — never stored on the instance or logged.

- FR-1.3: The `get_watched_items` method shall call `GET /Users/{user_id}/Items` with these query parameters:
  - `IsPlayed=true` — filter to watched items only.
  - `IncludeItemTypes=Movie` — filter to movies only (consistent with all other item queries in the codebase).
  - `SortBy=DatePlayed` — sort by most recently played.
  - `SortOrder=Descending` — most recent first.
  - `Recursive=true` — search all libraries.
  - No `Fields` parameter — the method does not need full metadata fields (Overview, Genres, etc.) since the purpose is activity tracking. Jellyfin includes `UserData` (containing `PlayCount`, `LastPlayedDate`, `IsFavorite`, `Played`) by default without requesting it.
  - Pagination parameters `StartIndex` and `Limit` — the method auto-paginates through all results.

- FR-1.4: The method shall auto-paginate through all results, following the same loop pattern as `get_all_items`: start at `StartIndex=0`, request pages of 200 items, increment `StartIndex` by the number of items received, stop when `StartIndex >= TotalRecordCount` or an empty page is received. There is no hard cap on the number of items returned — a limit would be a correctness bug for the downstream ranking service, which needs the complete watch history.

- FR-1.5: The method shall parse each item in the paginated response into a `WatchHistoryEntry` using a static parser method:
  ```python
  @staticmethod
  def _parse_watch_entry(item: dict[str, Any]) -> WatchHistoryEntry:
  ```
  The parser extracts:
  - `jellyfin_id` from `item["Id"]`.
  - `last_played_date` from `item["UserData"]["LastPlayedDate"]` — parsed as ISO 8601 datetime. `None` if the field is absent or null.
  - `play_count` from `item["UserData"]["PlayCount"]` — defaults to `0` if absent.
  - `is_favorite` from `item["UserData"]["IsFavorite"]` — defaults to `False` if absent.

- FR-1.6: The method shall use `_request` and `_parse_response` for HTTP communication and error handling, consistent with `get_items`. It shall raise `JellyfinAuthError` on 401, `JellyfinConnectionError` on transport failure, and `JellyfinError` on other non-2xx responses — the same error contract as all existing client methods.

- FR-1.7: The method shall log at DEBUG: page number and item count per page (e.g., `"watched_items_fetch page=%d items=%d"`). It shall never log the token, user_id paired with item data, or any PII.

**Proof Artifacts:**

- **Unit test**: `WatchHistoryEntry` dataclass is immutable (`frozen=True`) — verify that assigning to a field raises `FrozenInstanceError`.
- **Unit test**: `WatchHistoryEntry` fields have correct types and defaults are not applied (all fields are required except `last_played_date` which is `datetime | None`).
- **Unit test**: `get_watched_items` sends correct URL (`/Users/{user_id}/Items`), correct query parameters (`IsPlayed=true`, `IncludeItemTypes=Movie`, `SortBy=DatePlayed`, `SortOrder=Descending`, `Recursive=true`), and no `Fields` parameter. Mock `httpx.AsyncClient.request`.
- **Unit test**: `get_watched_items` parses a mock Jellyfin response into `list[WatchHistoryEntry]` with correct field values, including `last_played_date` as a `datetime` object.
- **Unit test**: `get_watched_items` auto-paginates — mock two pages (e.g., 200 + 50 items, `TotalRecordCount=250`), verify all 250 entries are returned.
- **Unit test**: `get_watched_items` returns an empty list for a user with no watch history (mock response: `Items=[], TotalRecordCount=0`).
- **Unit test**: `get_watched_items` handles missing `UserData` gracefully — `last_played_date=None`, `play_count=0`, `is_favorite=False`.
- **Unit test**: `get_watched_items` raises `JellyfinAuthError` on 401 response.
- **Unit test**: `get_watched_items` raises `JellyfinConnectionError` on transport error.
- **Unit test**: `get_watched_items` raises `JellyfinError` on 500 response.

---

### Unit 2: get_favorite_items Method

**Purpose:** Add a `get_favorite_items` method to `JellyfinClient` that fetches all favorited items for a user, using the same `WatchHistoryEntry` return type and auto-pagination pattern.

**Functional Requirements:**

- FR-2.1: The system shall add a `get_favorite_items` method to `JellyfinClient` with this signature:
  ```python
  async def get_favorite_items(
      self,
      token: str,
      user_id: str,
  ) -> list[WatchHistoryEntry]:
  ```
  Same parameter and token-handling discipline as `get_watched_items`.

- FR-2.2: The method shall call `GET /Users/{user_id}/Items` with these query parameters:
  - `IsFavorite=true` — filter to favorited items only.
  - `IncludeItemTypes=Movie` — movies only.
  - `Recursive=true` — search all libraries.
  - No explicit `SortBy` or `SortOrder` — Jellyfin applies its default sort order. The downstream ranking service (#119) will re-order results based on its own scoring, so the API sort order is irrelevant.
  - No `Fields` parameter — same rationale as `get_watched_items`.
  - Pagination parameters `StartIndex` and `Limit` for auto-pagination.

- FR-2.3: The method shall auto-paginate through all results using the same loop pattern as `get_watched_items` (FR-1.4). No hard cap.

- FR-2.4: The method shall parse each item into a `WatchHistoryEntry` using the same `_parse_watch_entry` static method (FR-1.5). For favorited items that have not been played, `last_played_date` will be `None` and `play_count` will be `0` — this is expected and correct.

- FR-2.5: The method shall use `_request` and `_parse_response` for HTTP communication and error handling, with the same error contract as all existing client methods (FR-1.6).

- FR-2.6: The method shall log at DEBUG: page number and item count per page (e.g., `"favorite_items_fetch page=%d items=%d"`). Same logging discipline as FR-1.7.

**Proof Artifacts:**

- **Unit test**: `get_favorite_items` sends correct URL and query parameters (`IsFavorite=true`, `IncludeItemTypes=Movie`, `Recursive=true`). Verify no `SortBy` or `SortOrder` parameters are sent. Verify no `Fields` parameter is sent.
- **Unit test**: `get_favorite_items` parses a mock response into `list[WatchHistoryEntry]` with correct field values.
- **Unit test**: `get_favorite_items` auto-paginates — mock two pages, verify all entries returned.
- **Unit test**: `get_favorite_items` returns an empty list for a user with no favorites.
- **Unit test**: `get_favorite_items` correctly parses a favorite item that has never been played (`last_played_date=None`, `play_count=0`, `is_favorite=True`).
- **Unit test**: `get_favorite_items` raises `JellyfinAuthError` on 401.
- **Unit test**: `get_favorite_items` raises `JellyfinConnectionError` on transport error.
- **Unit test**: `get_favorite_items` raises `JellyfinError` on 500.

---

### Unit 3: Test Suite

**Purpose:** Comprehensive unit tests and one integration test verifying the watch history client methods against both mocked and real Jellyfin instances.

**Functional Requirements:**

- FR-3.1: The system shall add unit tests in `backend/tests/test_watch_history.py` covering all proof artifacts from Units 1 and 2. Tests shall use the existing `mock_http` / `jf_client` fixture pattern from `test_jellyfin_client.py`:
  ```python
  @pytest.fixture
  def mock_http() -> AsyncMock:
      return AsyncMock(spec=httpx.AsyncClient)

  @pytest.fixture
  def jf_client(mock_http: AsyncMock) -> JellyfinClient:
      return JellyfinClient(
          base_url="http://jellyfin:8096",
          http_client=mock_http,
      )
  ```

- FR-3.2: Unit tests shall verify HTTP request construction by inspecting `mock_http.request.call_args`:
  - Correct HTTP method (`GET`).
  - Correct URL path (`/Users/{user_id}/Items`).
  - Correct query parameters for each method.
  - Token passed in the Authorization header via `_headers`.

- FR-3.3: Unit tests shall verify response parsing with representative Jellyfin JSON fixtures. The fixture data shall include realistic `UserData` objects:
  ```json
  {
    "Id": "item-1",
    "Name": "Alien",
    "Type": "Movie",
    "UserData": {
      "PlayCount": 3,
      "IsFavorite": true,
      "Played": true,
      "LastPlayedDate": "2025-12-15T20:30:00.0000000Z"
    }
  }
  ```

- FR-3.4: Unit tests shall verify error handling: 401 -> `JellyfinAuthError`, transport error -> `JellyfinConnectionError`, 500 -> `JellyfinError`. These follow the exact same test patterns as `TestGetItems` and `TestGetUser` in `test_jellyfin_client.py`.

- FR-3.5: Unit tests shall verify pagination by mocking multiple sequential responses from `mock_http.request`, verifying that:
  - The method makes the correct number of HTTP calls.
  - `StartIndex` increments correctly across pages.
  - All items from all pages are collected into the returned list.

- FR-3.6: Unit tests shall verify edge cases:
  - Empty `UserData` or missing `UserData` key on an item: `last_played_date=None`, `play_count=0`, `is_favorite=False`.
  - `LastPlayedDate` is null/absent: `last_played_date=None`.
  - `PlayCount` is absent: `play_count=0`.
  - `IsFavorite` is absent: `is_favorite=False`.
  - `UserData` is present but an empty dict `{}`: `last_played_date=None`, `play_count=0`, `is_favorite=False`.

- FR-3.7: The system shall add one integration test in `backend/tests/integration/test_jellyfin_client.py` (or a new `test_watch_history.py` in the integration directory) that:
  - Authenticates as test user `alice` against the real Jellyfin instance.
  - Calls `get_watched_items` and verifies it returns `list[WatchHistoryEntry]` (the list will be empty since the test Jellyfin has no library content — this verifies the API shape and empty-list handling against real Jellyfin).
  - Calls `get_favorite_items` and verifies the same.
  - Uses the `@pytest.mark.integration` marker.

- FR-3.8: All tests shall pass with `make test` (unit) and `make test-integration` (integration, requires `make jellyfin-up`).

- FR-3.9: All new code shall pass `make lint` (ruff).

**Proof Artifacts:**

- `make test` passes with all new unit tests.
- `make test-integration` passes with the empty-list integration test (requires `make jellyfin-up`).
- `make lint` passes with all new modules.
- Test coverage for `get_watched_items` and `get_favorite_items` includes: success path, pagination, empty list, missing UserData fields, auth error, connection error, unexpected status.

## Non-Goals (Out of Scope)

1. **Ranking logic** — This spec provides the raw data. How watch history and favorites influence recommendation ranking is #119's concern.
2. **Caching** — No in-memory caching of watch history or favorites. The ranking service (#119) will decide if caching is needed and at what layer. Adding premature caching here adds complexity for no demonstrated benefit.
3. **Service wrapper** — No `WatchHistoryService` class. The methods live directly on `JellyfinClient` as thin HTTP wrappers. A service layer is deferred to #119 if it needs to combine watched + favorites, apply caching, or orchestrate multiple calls.
4. **API endpoints** — No REST endpoints for watch history. These are internal client methods consumed by the ranking service, not exposed to the frontend.
5. **Watch history persistence** — Watch history is fetched live from Jellyfin on each ranking request. It is not stored in `library.db` or any local database. Jellyfin is the source of truth for user activity data.
6. **Series/episode support** — Only `Movie` items are fetched. Series and episode watch history is out of scope for the movie recommendation engine.
7. **Full metadata in return type** — `WatchHistoryEntry` deliberately excludes title, overview, genres, and other catalog metadata. That data is already in `library_items` from sync. Fetching it again in the watch history call would be redundant network and memory overhead.

## Design Considerations

No UI/UX considerations. This is a backend-only spec adding internal client methods with no user-facing interface.

### Return Type Design

`WatchHistoryEntry` is a `@dataclass(frozen=True, slots=True)` — not a Pydantic model. This follows the precedent set by `_CacheEntry` in `PermissionService` and `LibraryItemRow` in the library store: internal data transfer objects that don't need Pydantic's validation overhead. The Jellyfin response is validated structurally by the parser; the dataclass provides type safety for downstream consumers.

The model intentionally does NOT extend `LibraryItem`. These represent different domains:
- `LibraryItem` = library-scoped catalog metadata (titles, genres, studios) used for sync and embedding.
- `WatchHistoryEntry` = user-scoped activity metadata (play count, last played date) used for ranking.

Mixing them would create a model that is sometimes partially populated depending on the call context, which is an antipattern.

### Pagination Strategy

Both methods fetch ALL matching items with no limit parameter. This matches the `PermissionService._fetch_permitted_ids` pattern, which also consumes the full `get_all_items` iterator to build a complete set. The rationale: a hard cap on watch history would be a correctness bug for ranking. If a user has watched 500 movies and we only fetch 50, the ranker cannot distinguish "unwatched" from "watched but not in the top 50." The ranking service needs the full picture.

### Jellyfin Fields Strategy

The methods do not send a `Fields` parameter. Jellyfin's `/Users/{userId}/Items` endpoint includes `UserData` (containing `PlayCount`, `LastPlayedDate`, `IsFavorite`, `Played`) by default without requesting it. Since `WatchHistoryEntry` only needs fields from `UserData` plus the item `Id`, there is no reason to request the full metadata fields (`Overview`, `Genres`, `ProductionYear`, etc.) that `get_items` requests via `_ITEM_FIELDS`.

## Repository Standards

### Existing Patterns This Implementation Must Follow

- **`_request` / `_parse_response` / `_headers`**: All HTTP communication goes through the existing helper methods in `JellyfinClient` (lines 65-114 of `client.py`). New methods do not create their own HTTP calls or headers.
- **Token as parameter, never stored**: Matches `get_items(token, user_id, ...)`, `get_all_items(token, user_id, ...)`, and `get_user(token)` — tokens are call parameters, never instance state.
- **Per-user endpoint**: Uses `/Users/{user_id}/Items` so Jellyfin enforces per-user permissions and returns user-specific `UserData`, matching `get_items`.
- **Error contract**: Same three-tier error hierarchy as all existing client methods: `JellyfinAuthError` (401), `JellyfinConnectionError` (transport), `JellyfinError` (other non-2xx).
- **Test fixtures**: Unit tests use the `mock_http` / `jf_client` / `_FAKE_REQUEST` pattern from `test_jellyfin_client.py`. Integration tests use the `jellyfin` / `jf_client` / `test_users` fixture chain from `tests/integration/conftest.py`.
- **Conventional commits**: `feat(jellyfin):`, `test(jellyfin):`.

### File Organization

```
backend/app/
└── jellyfin/
    ├── client.py      # + get_watched_items(), get_favorite_items()
    └── models.py      # + WatchHistoryEntry dataclass

backend/tests/
├── test_watch_history.py                    # Unit tests (new file)
└── integration/
    └── test_jellyfin_client.py              # + empty-list integration tests
```

## Technical Considerations

- **Dependency on existing `JellyfinClient` infrastructure**: Both methods reuse `_request`, `_parse_response`, `_headers`, and the error handling from `client.py`. No new HTTP client instances or connection pools.
- **`UserData` availability**: Jellyfin automatically includes `UserData` on items fetched via `/Users/{userId}/Items` without needing to request it via the `Fields` parameter. This has been verified by inspecting Jellyfin's API behavior and is consistent with how `IsPlayed` and `IsFavorite` filters work (they filter on `UserData` fields, which implies `UserData` is present in the response).
- **ISO 8601 datetime parsing**: `LastPlayedDate` from Jellyfin is an ISO 8601 string (e.g., `"2025-12-15T20:30:00.0000000Z"`). The parser shall use `datetime.fromisoformat()` (Python 3.11+), which handles the `Z` suffix and fractional seconds. If the field is absent or null, `last_played_date` is `None`.
- **Pagination page size**: Uses 200 items per page, matching the default `page_size` in `get_all_items`. This is not configurable — it is an internal implementation detail, not a user-facing setting.
- **Memory footprint**: `WatchHistoryEntry` has 4 fields (~100 bytes per entry). A user with 1,000 watched movies produces ~100 KB of entries. Negligible.
- **Feeds into #119**: The history-aware ranking service will call both `get_watched_items` and `get_favorite_items` with the user's session token, then use the returned entries to adjust vector search result scores. The slim DTO avoids fetching redundant metadata that is already in `library_items`.

## Security Considerations

- **Token passed as parameter, never stored**: Both methods accept `token` as a call parameter, pass it to `_request` via `_headers`, and never store it on `self`, in a cache, or in a log message. Identical discipline to `get_items`, `get_user`, and all other client methods.
- **Per-user endpoint**: Using `/Users/{user_id}/Items` ensures Jellyfin enforces that user's specific library access and parental restrictions. The response only contains items the authenticated user is permitted to see.
- **No PII in logs**: Log messages include page numbers and item counts only. Never log token values, user_id paired with item data, or item metadata.
- **No token in error messages**: Exception messages from `_request` do not include the token value (verified by the existing `_request` implementation).
- **No admin API key usage**: Watch history is inherently per-user data. These methods always use the user's own session token, never `JELLYFIN_API_KEY`.

## Success Metrics

1. `get_watched_items` returns a complete `list[WatchHistoryEntry]` for a user's played items, auto-paginating through all pages — verified by unit test with mocked multi-page responses.
2. `get_favorite_items` returns a complete `list[WatchHistoryEntry]` for a user's favorited items — verified by unit test.
3. `WatchHistoryEntry` correctly captures `jellyfin_id`, `last_played_date` (as `datetime | None`), `play_count` (as `int`), and `is_favorite` (as `bool`) — verified by unit tests with representative Jellyfin JSON.
4. Both methods handle missing/null `UserData` fields gracefully with safe defaults — verified by unit tests.
5. Both methods raise the correct domain exceptions (`JellyfinAuthError`, `JellyfinConnectionError`, `JellyfinError`) — verified by unit tests.
6. Both methods send correct Jellyfin query parameters — verified by unit tests inspecting `mock_http.request.call_args`.
7. Neither method sends a `Fields` parameter (no unnecessary metadata fetching) — verified by unit test.
8. Integration test confirms both methods return `list[WatchHistoryEntry]` (empty list) against a real Jellyfin instance — verified by `make test-integration`.
9. `make test` and `make lint` pass with all new code.

## Open Questions

None. All six design questions were resolved in the decision packet before spec generation (documented in `17-questions-1-watch-history-client.md`).
