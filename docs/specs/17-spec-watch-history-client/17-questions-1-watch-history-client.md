# 17 Questions Round 1 - Watch History Client

Please answer each question below (select one or more options, or add your own notes). Feel free to add additional context under any question.

## 1. Return Model and Watch-Specific Fields

The issue says the methods return `list[LibraryItem]`, but the downstream consumer (#119 history-aware ranking) will need temporal data like when an item was last played, how many times it was played, and whether it was marked as a favorite. The current `LibraryItem` model has no fields for `DatePlayed`, `PlayCount`, or `IsFavorite`.

**Should the methods return the existing `LibraryItem` or a new model that includes watch-specific metadata?**

- [ ] (A) Return `list[LibraryItem]` as-is — ranking in #119 only needs the item IDs, not temporal data
- [ ] (B) Add optional fields to `LibraryItem` (e.g. `last_played_date`, `play_count`, `is_favorite`) that are `None` when not relevant — keeps one model, avoids proliferation
- [ ] (C) Create a new `WatchedItem` model that wraps or extends `LibraryItem` with watch-specific fields (`last_played_date: datetime | None`, `play_count: int`, `is_favorite: bool`) — clean separation between library sync data and user activity data
- [ ] (D) Return a slim DTO with just the fields ranking needs (item ID, last played date, play count) — the full metadata is already in the local `library_items` table from sync

Notes:

## 2. Jellyfin Fields to Request

The existing `get_items` method requests `_ITEM_FIELDS` (Overview, Genres, ProductionYear, Tags, Studios, CommunityRating, People) which is optimised for embedding/display. Watch history queries may not need all that metadata (especially if items are already synced locally), but Jellyfin's `UserData` object (containing `PlayCount`, `LastPlayedDate`, `IsFavorite`, `Played`) comes back automatically without requesting it — it just needs to not be stripped.

**Should the watch history methods request the full `_ITEM_FIELDS`, a minimal set, or just rely on UserData?**

- [ ] (A) Request full `_ITEM_FIELDS` — same as sync, keeps things consistent, data is there if we need it
- [ ] (B) Request minimal fields (just `UserData`) since the purpose is activity tracking, not metadata — full metadata is already in local SQLite from sync
- [ ] (C) Let this decision follow from Q1 — if we return `LibraryItem`, use `_ITEM_FIELDS`; if we return a slim DTO, use minimal fields

Notes:

## 3. Pagination Strategy

The issue says "Paginated fetching with existing `get_all_items` pattern" but also specifies a `limit=50` default parameter. The `get_all_items` method auto-paginates through ALL items. For a user who has watched hundreds of movies, these two patterns are contradictory.

**Should the limit be a hard cap (fetch at most N items) or should the methods auto-paginate through all history?**

- [ ] (A) Hard cap — `limit` is the maximum number of items returned. If a user watched 500 movies, `limit=50` returns the 50 most recent. Simple, bounded, predictable cost
- [ ] (B) Auto-paginate all — use the `get_all_items` pattern to fetch everything, ignore the limit param. Downstream ranking can decide how many to use
- [ ] (C) Default hard cap (e.g. 50), but accept `limit=None` to mean "fetch all" for cases where the caller explicitly wants everything

Notes:

## 4. Integration Test Strategy

The existing integration tests run against a disposable Jellyfin container with provisioned test users (alice, bob). To test `get_watched_items` and `get_favorite_items`, we need items that are actually marked as played/favorited. The test Jellyfin currently has no library content.

**How should integration tests handle the need for watched/favorited items?**

- [ ] (A) Use Jellyfin's API to mark items as played/favorited during test setup — but this requires library items to exist first. Add a fixture that creates dummy items or imports a small test library
- [ ] (B) Test only the "no history" empty-list case in integration tests — the API shape and error handling are the important things to verify against real Jellyfin. Unit tests cover the parsing with mocked responses
- [ ] (C) Skip integration tests for now — unit tests with mocked HTTP responses are sufficient for a 2-point client method. Add integration tests when #119 (ranking) needs end-to-end verification
- [ ] (D) Provision a small test media library (a few public-domain clips or dummy items) in the test Jellyfin, then mark some as played/favorited in test setup

Notes:

## 5. Favorites Sort Order

For watched items, the issue specifies `SortBy=DatePlayed&SortOrder=Descending` (most recently played first), which is clear. For favorites, no sort order is specified.

**What sort order should `get_favorite_items` use?**

- [ ] (A) `SortBy=DateCreated&SortOrder=Descending` — most recently added favorites first
- [ ] (B) `SortBy=SortName` — alphabetical, matching Jellyfin's default
- [ ] (C) `SortBy=DatePlayed&SortOrder=Descending` — same as watched items, so recently-played favorites surface first (useful for ranking)
- [ ] (D) No explicit sort — let Jellyfin decide the default, since ranking in #119 will re-order anyway

Notes:

## 6. Method Placement

The issue specifies these as `JellyfinClient` methods, which is consistent with the existing pattern (all Jellyfin HTTP calls live in `client.py`). However, the permission service shows an alternative pattern where a higher-level service wraps the client.

**Confirm: should `get_watched_items` and `get_favorite_items` be methods directly on `JellyfinClient`?**

- [ ] (A) Yes, on `JellyfinClient` — they are thin HTTP wrappers, same as `get_items`. Keep the client as the single place for all Jellyfin API calls
- [ ] (B) Create a separate `WatchHistoryService` that wraps `JellyfinClient` — adds a layer for future caching, combining watched + favorites, etc. Client stays focused on raw HTTP

Notes:
