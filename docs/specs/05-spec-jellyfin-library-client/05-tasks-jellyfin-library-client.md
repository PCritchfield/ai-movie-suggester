# 05 Tasks - Jellyfin Library Client

## Relevant Files

### Files to Create
- `backend/app/library/__init__.py` — module init
- `backend/app/library/models.py` — `LibraryItemRow`, `UpsertResult`, `LibraryStoreProtocol`
- `backend/app/library/store.py` — `LibraryStore` (SQLite repository)
- `backend/app/library/hashing.py` — placeholder content-hash function
- `backend/tests/test_library_store.py` — unit tests for `LibraryStore`
- `backend/tests/integration/test_jellyfin_library.py` — integration test for full fetch+store cycle

### Files to Modify
- `backend/app/jellyfin/models.py` — extend `LibraryItem` with tags, studios, community_rating, people
- `backend/app/jellyfin/client.py` — update `_ITEM_FIELDS`, add `get_all_items()` async iterator
- `backend/app/config.py` — add `library_db_path`, `jellyfin_api_key`, `library_sync_page_size`
- `backend/app/main.py` — wire `LibraryStore` into lifespan, create sync `JellyfinClient`
- `backend/tests/test_jellyfin_client.py` — add tests for extended `LibraryItem` and `get_all_items()`
- `backend/tests/test_config.py` — add tests for new config fields (`jellyfin_api_key`, `library_db_path`, `library_sync_page_size`)
- `.env.example` — add `JELLYFIN_API_KEY`, `LIBRARY_DB_PATH`, `LIBRARY_SYNC_PAGE_SIZE` entries
- `ARCHITECTURE.md` — document two-database strategy and credential distinction

---

## Tasks

### [~] 1.0 Extended LibraryItem Model + Auto-Paginated Client

Extend the `LibraryItem` Pydantic model with fields needed for embedding (tags, studios, community_rating, people) and add `get_all_items()` async iterator to `JellyfinClient` for auto-paginated library fetching. Add `LIBRARY_SYNC_PAGE_SIZE` to `Settings`.

#### 1.0 Proof Artifact(s)
- Test: `backend/tests/test_jellyfin_client.py::TestLibraryItem` — new fields parse correctly from representative Jellyfin JSON, defaults when fields absent, `Studios` validator extracts names from objects
- Test: `backend/tests/test_jellyfin_client.py::TestGetAllItems` — mock `get_items()` returning two pages (200 + 50 items, `total_count=250`), verify iterator yields exactly two pages, stops after second page
- Test: `backend/tests/test_jellyfin_client.py::TestGetAllItems::test_empty_library` — iterator yields one page with zero items and stops
- Test: `backend/tests/test_jellyfin_client.py::TestGetAllItems::test_auth_error_propagates` — `JellyfinAuthError` propagates on first page
- Test: `backend/tests/test_jellyfin_client.py::TestGetAllItems::test_mid_pagination_error` — `JellyfinConnectionError` propagates after yielding the first page
- Verify: `_ITEM_FIELDS` in `backend/app/jellyfin/client.py` includes `Tags,Studios,CommunityRating,People`
- Verify: `LIBRARY_SYNC_PAGE_SIZE` in `backend/app/config.py` defaults to `200`

#### 1.0 Tasks

**Model extensions (`backend/app/jellyfin/models.py`)**
- [ ] 1.1 Add `tags: list[str]` field to `LibraryItem` with `Field(default_factory=list, alias="Tags")`
- [ ] 1.2 Add `studios: list[str]` field to `LibraryItem` with `Field(default_factory=list, alias="Studios")` and a `@field_validator("studios", mode="before")` that extracts `Name` from each studio object (handles both `[{"Name": "Pixar", "Id": "..."}]` and plain `["Pixar"]` formats)
- [ ] 1.3 Add `community_rating: float | None` field to `LibraryItem` with `Field(default=None, alias="CommunityRating")`
- [ ] 1.4 Add `people: list[dict[str, str]]` field to `LibraryItem` with `Field(default_factory=list, alias="People")` — raw Jellyfin People array (each entry has Name, Role, Type)

**Client extensions (`backend/app/jellyfin/client.py`)**
- [ ] 1.5 Update `_ITEM_FIELDS` constant to include `Tags,Studios,CommunityRating,People` (append to existing `Overview,Genres,ProductionYear`)
- [ ] 1.6 Add `async def get_all_items(self, token: str, user_id: str, *, item_types: list[str] | None = None, page_size: int = 200) -> AsyncIterator[PaginatedItems]` method that auto-paginates by calling `get_items()` in a loop, yielding each page, incrementing `start_index` by items received, stopping when `start_index >= total_count`
- [ ] 1.7 Add DEBUG logging in `get_all_items()` for page number and item count per page (never log `user_id` paired with item data)
- [ ] 1.8 Ensure `get_all_items()` propagates `JellyfinAuthError` and `JellyfinConnectionError` from underlying `get_items()` without catching them (FR-1.6)
- [ ] 1.9 Ensure token parameter in `get_all_items()` is passed through to `get_items()` on each call, never stored as an instance attribute (FR-1.7)

**Config extension (`backend/app/config.py`)**
- [ ] 1.10 Add `library_sync_page_size: int = 200` field to `Settings` class

**Unit tests — model (`backend/tests/test_jellyfin_client.py::TestLibraryItem`)**
- [ ] 1.11 Add test: `LibraryItem` parses all new fields (tags, studios, community_rating, people) from representative Jellyfin JSON with all fields present
- [ ] 1.12 Add test: `LibraryItem` defaults new fields correctly when absent (tags=[], studios=[], community_rating=None, people=[])
- [ ] 1.13 Add test: `Studios` validator extracts `Name` from studio objects (`[{"Name": "Pixar", "Id": "abc"}]` -> `["Pixar"]`)
- [ ] 1.14 Add test: `Studios` validator handles plain string list input gracefully
- [ ] 1.15 Add test: `People` field parses raw Jellyfin People array with Name, Role, Type dicts

**Unit tests — get_all_items (`backend/tests/test_jellyfin_client.py::TestGetAllItems`)**
- [ ] 1.16 Add test: mock `get_items()` returning two pages (page 1: 200 items, page 2: 50 items, `total_count=250`), verify iterator yields exactly two `PaginatedItems`, verify it stops after second page
- [ ] 1.17 Add test: empty library — mock `get_items()` returning `PaginatedItems(items=[], total_count=0, start_index=0)`, verify iterator yields one page and stops
- [ ] 1.18 Add test: `JellyfinAuthError` on first page propagates immediately
- [ ] 1.19 Add test: `JellyfinConnectionError` on second page propagates after first page was successfully yielded
- [ ] 1.20 Add test: verify `_ITEM_FIELDS` includes `Tags`, `Studios`, `CommunityRating`, `People`

**Unit test — config (`backend/tests/test_config.py`)**
- [ ] 1.21 Add test: `library_sync_page_size` defaults to `200`

---

### [ ] 2.0 Library Metadata Store (SQLite Repository)

Create `backend/app/library/` module with `LibraryStore` (SQLite repository following `SessionStore` pattern), `LibraryItemRow` and `UpsertResult` dataclasses, `LibraryStoreProtocol`, and placeholder content-hash function. Implements bulk upsert with created/updated/unchanged tracking, single/batch get, hash retrieval, and count.

#### 2.0 Proof Artifact(s)
- Test: `backend/tests/test_library_store.py::TestInit` — table and indexes created, WAL mode enabled, `PRAGMA foreign_keys` is ON
- Test: `backend/tests/test_library_store.py::TestUpsertMany` — insert 3 new items yields `UpsertResult(created=3, updated=0, unchanged=0)`; re-upsert same items yields `UpsertResult(created=0, updated=0, unchanged=3)`; change one hash yields `UpsertResult(created=0, updated=1, unchanged=2)`
- Test: `backend/tests/test_library_store.py::TestGet` — fetch existing item with all fields round-tripping correctly (including JSON arrays); fetch missing ID returns `None`
- Test: `backend/tests/test_library_store.py::TestGetMany` — insert 5, fetch 3 by ID, verify 3 returned; mix in non-existent IDs, verify only existing returned
- Test: `backend/tests/test_library_store.py::TestGetAllHashes` — verify returned dict maps `jellyfin_id` to `content_hash` for all items
- Test: `backend/tests/test_library_store.py::TestCount` — empty store returns 0, after inserting 5 returns 5
- Test: `backend/tests/test_library_store.py::TestContentHash` — deterministic output; different input produces different hash
- Test: `backend/tests/test_library_store.py::TestPeopleFiltering` — non-Actor entries excluded from stored `people` list
- Test: `backend/tests/test_library_store.py::TestValidation` — malformed Jellyfin item data skipped with WARNING log, valid items stored
- File: `backend/app/library/__init__.py` exists
- File: `backend/app/library/models.py` contains `LibraryItemRow`, `UpsertResult`, `LibraryStoreProtocol`
- File: `backend/app/library/store.py` contains `LibraryStore`
- File: `backend/app/library/hashing.py` contains placeholder hash function with `# TODO: Replace with text_builder from Spec 07`
- Verify: `backend/app/config.py` includes `library_db_path` setting defaulting to `"data/library.db"`

#### 2.0 Tasks

**Module scaffolding**
- [ ] 2.1 Create `backend/app/library/__init__.py` as empty module file
- [ ] 2.2 Create `backend/app/library/models.py` with `LibraryItemRow` frozen dataclass (fields: `jellyfin_id`, `title`, `overview`, `production_year`, `genres`, `tags`, `studios`, `community_rating`, `people`, `content_hash`, `synced_at`) using `@dataclass(frozen=True, slots=True)`
- [ ] 2.3 Add `UpsertResult` frozen dataclass to `backend/app/library/models.py` with fields: `created: int`, `updated: int`, `unchanged: int`
- [ ] 2.4 Add `LibraryStoreProtocol` to `backend/app/library/models.py` following `SessionStoreProtocol` pattern, defining: `init()`, `close()`, `upsert_many()`, `get()`, `get_many()`, `get_all_hashes()`, `count()`

**Content hashing (`backend/app/library/hashing.py`)**
- [ ] 2.5 Create `backend/app/library/hashing.py` with `def compute_content_hash(item: LibraryItemRow) -> str` that builds a deterministic string from item fields (sorted JSON arrays, consistent field ordering, normalized whitespace) and returns `hashlib.sha256(...).hexdigest()`
- [ ] 2.6 Add `# TODO: Replace with text_builder from Spec 07` comment in the function, documenting field ordering used

**Config extension (`backend/app/config.py`)**
- [ ] 2.7 Add `library_db_path: str = "data/library.db"` field to `Settings` class

**Library store (`backend/app/library/store.py`)**
- [ ] 2.8 Create `LibraryStore` class with `__init__(self, db_path: str)`, following `SessionStore` structural pattern
- [ ] 2.9 Implement `async def init(self) -> None` — opens aiosqlite connection, enables WAL mode (`PRAGMA journal_mode=WAL`), enables `PRAGMA foreign_keys = ON`, creates `library_items` table with schema from FR-2.4, creates `idx_library_items_content_hash` and `idx_library_items_synced_at` indexes
- [ ] 2.10 Implement `async def close(self) -> None` — closes the connection, sets `_db` to `None`
- [ ] 2.11 Implement `_conn` property that raises `RuntimeError("LibraryStore not initialised — call init() first")` if `_db` is `None`
- [ ] 2.12 Implement `async def upsert_many(self, items: list[LibraryItemRow]) -> UpsertResult` — wraps batch in single transaction, fetches existing hashes in bulk first, uses `INSERT INTO ... ON CONFLICT(jellyfin_id) DO UPDATE SET ...` (never `INSERT OR REPLACE`), serializes JSON arrays via `json.dumps()`, tracks created/updated/unchanged by comparing content_hash
- [ ] 2.13 Implement `async def get(self, jellyfin_id: str) -> LibraryItemRow | None` — fetch single item by primary key, deserialize JSON arrays via `json.loads()`, return `None` if not found
- [ ] 2.14 Implement `async def get_many(self, ids: list[str]) -> list[LibraryItemRow]` — fetch multiple items with `WHERE jellyfin_id IN (?, ?, ...)` using parameterized queries (no string interpolation), chunk into batches of 500 if list exceeds safe threshold, return items in no guaranteed order
- [ ] 2.15 Implement `async def get_all_hashes(self) -> dict[str, str]` — return `{jellyfin_id: content_hash}` mapping for all items
- [ ] 2.16 Implement `async def count(self) -> int` — return total number of items in the store
- [ ] 2.17 Add helper `_row_to_item()` method to deserialize a database row into `LibraryItemRow`, parsing JSON text columns back to lists

**Unit tests — init (`backend/tests/test_library_store.py::TestInit`)**
- [ ] 2.18 Add test: after `init()`, `library_items` table exists (query `sqlite_master`)
- [ ] 2.19 Add test: after `init()`, indexes `idx_library_items_content_hash` and `idx_library_items_synced_at` exist
- [ ] 2.20 Add test: after `init()`, `PRAGMA journal_mode` returns `wal`
- [ ] 2.21 Add test: after `init()`, `PRAGMA foreign_keys` returns `1`
- [ ] 2.22 Add test: calling `_conn` before `init()` raises `RuntimeError`

**Unit tests — upsert_many (`backend/tests/test_library_store.py::TestUpsertMany`)**
- [ ] 2.23 Add test: insert 3 new items, verify `UpsertResult(created=3, updated=0, unchanged=0)`
- [ ] 2.24 Add test: re-upsert same 3 items with same content_hash, verify `UpsertResult(created=0, updated=0, unchanged=3)`
- [ ] 2.25 Add test: change one item's content_hash and re-upsert all 3, verify `UpsertResult(created=0, updated=1, unchanged=2)`
- [ ] 2.26 Add test: upsert empty list, verify `UpsertResult(created=0, updated=0, unchanged=0)`

**Unit tests — get (`backend/tests/test_library_store.py::TestGet`)**
- [ ] 2.27 Add test: insert an item then fetch by ID, verify all fields round-trip correctly including JSON arrays (`genres`, `tags`, `studios`, `people`)
- [ ] 2.28 Add test: fetch non-existent ID returns `None`

**Unit tests — get_many (`backend/tests/test_library_store.py::TestGetMany`)**
- [ ] 2.29 Add test: insert 5 items, fetch 3 by ID, verify exactly 3 returned with correct data
- [ ] 2.30 Add test: fetch with mix of existing and non-existent IDs, verify only existing items returned
- [ ] 2.31 Add test: fetch with empty ID list, verify empty list returned

**Unit tests — get_all_hashes (`backend/tests/test_library_store.py::TestGetAllHashes`)**
- [ ] 2.32 Add test: insert items, verify returned dict maps each `jellyfin_id` to its `content_hash`
- [ ] 2.33 Add test: empty store returns empty dict

**Unit tests — count (`backend/tests/test_library_store.py::TestCount`)**
- [ ] 2.34 Add test: empty store returns `0`
- [ ] 2.35 Add test: after inserting 5 items, returns `5`

**Unit tests — content hash (`backend/tests/test_library_store.py::TestContentHash`)**
- [ ] 2.36 Add test: same `LibraryItemRow` input always produces the same hash (deterministic)
- [ ] 2.37 Add test: different input (e.g., changed title) produces a different hash

**Unit tests — people filtering (`backend/tests/test_library_store.py::TestPeopleFiltering`)**
- [ ] 2.38 Add test: `LibraryItemRow` with people list stores only actor names; verify non-Actor `People` entries from Jellyfin raw data are excluded when building the row (this tests the conversion logic from `LibraryItem.people` to `LibraryItemRow.people`)

**Unit tests — validation (`backend/tests/test_library_store.py::TestValidation`)**
- [ ] 2.39 Add test: malformed Jellyfin item data (missing required `Id` or `Name`) is skipped with a WARNING log (item ID only), valid items in the same batch are stored successfully

**Unit test — config (`backend/tests/test_config.py`)**
- [ ] 2.40 Add test: `library_db_path` defaults to `"data/library.db"`

---

### [ ] 3.0 App Wiring, Config, and Documentation

Wire `LibraryStore` into `main.py` lifespan (init after `SessionStore`, close before), add `JELLYFIN_API_KEY` config with whitespace validation, create sync-dedicated `JellyfinClient` instance when API key is set, update `.env.example` and `ARCHITECTURE.md`.

#### 3.0 Proof Artifact(s)
- Test: `backend/tests/test_main.py::TestLifespan` (or equivalent) — verify `LibraryStore.init()` called after `SessionStore.init()`, `LibraryStore.close()` called before `SessionStore.close()`
- Test: `backend/tests/test_config.py` (or equivalent) — empty/whitespace `JELLYFIN_API_KEY` treated as `None`; valid key stored in settings; API key never appears in log output
- Test: `backend/tests/integration/test_jellyfin_library.py` — connect to test Jellyfin, call `get_all_items(item_types=["Movie"])`, verify items returned with expected fields, store in `LibraryStore`, verify `count()` matches `total_count` from Jellyfin (marked `@pytest.mark.integration`)
- Verify: `.env.example` contains `JELLYFIN_API_KEY` with security warning comment block
- Verify: `.env.example` contains `LIBRARY_DB_PATH` and `LIBRARY_SYNC_PAGE_SIZE` entries
- Verify: `ARCHITECTURE.md` documents two-database strategy (`sessions.db` + `library.db`) and credential distinction (infrastructure API key vs. user tokens)
- Verify: `backend/app/library/__init__.py` exists as module file
- Verify: `app.state.library_store` is set during lifespan startup

#### 3.0 Tasks

**Config — API key (`backend/app/config.py`)**
- [ ] 3.1 Add `jellyfin_api_key: str | None = None` field to `Settings` class, loaded from `JELLYFIN_API_KEY` env var
- [ ] 3.2 Add `@model_validator(mode="after")` for `jellyfin_api_key` that strips whitespace and treats empty/whitespace-only values as `None`, logging a WARNING when a whitespace-only key is discarded
- [ ] 3.3 Ensure `jellyfin_api_key` never appears in log output — no `__repr__` or `__str__` exposure (Pydantic `SecretStr` or manual exclusion from any logging)

**Lifespan wiring (`backend/app/main.py`)**
- [ ] 3.4 Import `LibraryStore` from `app.library.store` in `main.py`
- [ ] 3.5 In lifespan startup, after `SessionStore.init()`: create `data/` directory for `library.db` if it does not exist (same pattern as session DB), instantiate `LibraryStore(settings.library_db_path)`, call `await library_store.init()`, store on `app.state.library_store`
- [ ] 3.6 In lifespan shutdown: close `LibraryStore` before closing `SessionStore` (reverse initialization order) — `await library_store.close()` before `await store.close()`
- [ ] 3.7 If `settings.jellyfin_api_key` is set, create a separate sync `JellyfinClient` instance using the same shared `httpx.AsyncClient` but a distinct `device_id` (e.g., `"ai-movie-suggester-sync"`), store on `app.state.sync_jellyfin_client`
- [ ] 3.8 If `settings.jellyfin_api_key` is not set, log INFO that background sync is disabled (API key not configured)

**Unit tests — config (`backend/tests/test_config.py`)**
- [ ] 3.9 Add test: `jellyfin_api_key` defaults to `None` when env var not set
- [ ] 3.10 Add test: valid `JELLYFIN_API_KEY` value is stored in settings
- [ ] 3.11 Add test: empty string `JELLYFIN_API_KEY=""` is treated as `None`
- [ ] 3.12 Add test: whitespace-only `JELLYFIN_API_KEY="   "` is treated as `None`
- [ ] 3.13 Add test: `JELLYFIN_API_KEY` with leading/trailing whitespace is stripped (e.g., `"  key123  "` -> `"key123"`)

**Unit tests — lifespan (`backend/tests/test_main.py`)**
- [ ] 3.14 Create `backend/tests/test_main.py` with `TestLifespan` class
- [ ] 3.15 Add test: verify `LibraryStore.init()` is called during startup (mock `LibraryStore`)
- [ ] 3.16 Add test: verify `app.state.library_store` is set after startup
- [ ] 3.17 Add test: verify `LibraryStore.close()` is called before `SessionStore.close()` during shutdown (use mock call ordering)
- [ ] 3.18 Add test: verify sync `JellyfinClient` is created on `app.state.sync_jellyfin_client` when `jellyfin_api_key` is set
- [ ] 3.19 Add test: verify `app.state.sync_jellyfin_client` is not set when `jellyfin_api_key` is `None`

**Integration test (`backend/tests/integration/test_jellyfin_library.py`)**
- [ ] 3.20 Create `backend/tests/integration/test_jellyfin_library.py` with `@pytest.mark.integration` marker
- [ ] 3.21 Add test: authenticate as admin, call `get_all_items(token, user_id, item_types=["Movie"])`, verify items are returned (may be 0 on fresh Jellyfin — test handles both cases)
- [ ] 3.22 Add test: fetch items via `get_all_items()`, convert to `LibraryItemRow` (using placeholder hash), store in a temporary `LibraryStore`, verify `count()` matches `total_count` from Jellyfin response
- [ ] 3.23 Add test: verify returned `LibraryItem` objects have the extended fields populated (tags, studios, community_rating, people — at minimum, no Pydantic validation errors)

**Documentation (`.env.example`)**
- [ ] 3.24 Add `# --- Library Sync ---` section to `.env.example` with `JELLYFIN_API_KEY` entry including the security warning comment block from FR-3.4 (how to generate, treat like root password, never commit)
- [ ] 3.25 Add `LIBRARY_DB_PATH` entry (commented out, showing default `data/library.db`)
- [ ] 3.26 Add `LIBRARY_SYNC_PAGE_SIZE` entry (commented out, showing default `200`)

**Documentation (`ARCHITECTURE.md`)**
- [ ] 3.27 Update "SQLite-vec" component section to document the two-file database strategy: `data/sessions.db` for auth/session data, `data/library.db` for item metadata and future vector embeddings, with rationale (different access patterns, backup lifecycles, WAL mode on both)
- [ ] 3.28 Add note under "Security Model" section distinguishing infrastructure credentials (`JELLYFIN_API_KEY` — operator-configured, server-scoped, enables background sync) from user tokens (per-session, encrypted at rest, never persisted to objects)
