# 05-spec-jellyfin-library-client

## Introduction/Overview

This spec extends the existing `JellyfinClient` to fetch a user's full movie library with auto-pagination, and introduces a SQLite metadata store (`library.db`) with content hashing for incremental sync. Together these components provide the data foundation that the embedding pipeline (Spec 07) and semantic search (Spec 06) build upon — the app cannot recommend movies it has never seen.

## Goals

- **Complete library fetching**: Auto-paginate the Jellyfin `/Users/{userId}/Items` endpoint to retrieve all movie items, yielding pages via an async iterator so memory usage stays bounded regardless of library size.
- **Persistent metadata store**: Store library item metadata in a SQLite repository (`library.db`) using the same `init()`/`close()`/`_conn` pattern as `SessionStore`, with upsert semantics for incremental sync.
- **Content-hash-driven sync**: Hash the composite text template output (SHA-256) and store it per item, so downstream consumers (embedding pipeline) can detect which items are new or changed without re-embedding the entire library.
- **Flexible sync credentials**: Support both user-triggered sync (session token passed as parameter) and background sync (optional `JELLYFIN_API_KEY` env var), with strict token-handling discipline — tokens are never stored on objects or logged.
- **Input validation**: All Jellyfin API data passes through Pydantic models before storage, preventing malformed or unexpected data from reaching the database.

## User Stories

- **As the server operator**, I want the backend to fetch my entire Jellyfin movie library so that the recommendation engine has complete knowledge of available content.
- **As a self-hoster with a large library**, I want library sync to be incremental (only re-processing changed items) so that sync completes quickly and doesn't waste CPU on unchanged content.
- **As a privacy-conscious user**, I want sync credentials to be handled securely — API keys never logged, user tokens never persisted to objects — so that credential exposure risk is minimized.
- **As a developer**, I want the library metadata store to follow the same repository patterns as `SessionStore` so that the codebase stays consistent and easy to navigate.

## Demoable Units of Work

### Unit 1: Extended LibraryItem Model + Auto-Paginated Client

**Purpose:** Extend the `LibraryItem` Pydantic model with all fields needed for embedding and recommendation, and add an auto-paginating async iterator to `JellyfinClient` that yields pages of library items until the entire library is fetched.

**Functional Requirements:**

- FR-1.1: The system shall extend `LibraryItem` in `backend/app/jellyfin/models.py` with the following optional fields (all with sensible defaults so existing code is unaffected):
  - `tags: list[str] = Field(default_factory=list, alias="Tags")` — user-assigned tags from Jellyfin.
  - `studios: list[str] = Field(default_factory=list, alias="Studios")` — parsed from Jellyfin's `Studios` array (extract `Name` from each studio object).
  - `community_rating: float | None = Field(default=None, alias="CommunityRating")` — Jellyfin's community/audience rating.
  - `people: list[dict[str, str]] = Field(default_factory=list, alias="People")` — raw Jellyfin People array (each entry has `Name`, `Role`, `Type`). Filtering to cast-only is the consumer's responsibility.
- FR-1.2: The system shall update the `_ITEM_FIELDS` constant in `backend/app/jellyfin/client.py` to include `Tags,Studios,CommunityRating,People` in addition to the existing `Overview,Genres,ProductionYear`.
- FR-1.3: The `Studios` field in Jellyfin's API returns an array of objects (`[{"Name": "Pixar", "Id": "..."}]`). The `LibraryItem` model shall use a Pydantic `@field_validator` (or equivalent) to extract the `Name` string from each studio object, storing `studios` as `list[str]`.
- FR-1.4: The system shall add a `LIBRARY_SYNC_PAGE_SIZE` setting to `Settings` in `backend/app/config.py`, defaulting to `200`. This controls the page size for library sync pagination.
- FR-1.5: The system shall add an `async def get_all_items()` method to `JellyfinClient` that auto-paginates by calling the existing `get_items()` in a loop, yielding each `PaginatedItems` page as it arrives. Signature:
  ```python
  async def get_all_items(
      self,
      token: str,
      user_id: str,
      *,
      item_types: list[str] | None = None,
      page_size: int = 200,
  ) -> AsyncIterator[PaginatedItems]:
  ```
  The method shall:
  1. Start at `start_index=0` and request `limit=page_size` items per call.
  2. Yield each `PaginatedItems` response.
  3. Increment `start_index` by the number of items received.
  4. Stop when `start_index >= total_count` from the response.
  5. Log at DEBUG: page number and item count per page. Never log user_id paired with item data.
- FR-1.6: The `get_all_items()` method shall propagate `JellyfinAuthError` and `JellyfinConnectionError` from the underlying `get_items()` calls without catching them. The caller is responsible for handling partial failure.
- FR-1.7: The token parameter in `get_all_items()` shall be passed through to `get_items()` on each call — never stored as an instance attribute.

**Proof Artifacts:**

- Unit tests for `LibraryItem` model: verify that all new fields parse correctly from representative Jellyfin JSON, verify defaults when fields are absent, verify `Studios` validator extracts names from objects.
- Unit tests for `get_all_items()`: mock `get_items()` to return two pages (e.g., 200 + 50 items with `total_count=250`), verify the iterator yields exactly two pages, verify it stops after the second page.
- Unit test for `get_all_items()` with an empty library: verify the iterator yields one page with zero items and stops.
- Unit test for `get_all_items()` auth error: verify `JellyfinAuthError` propagates on the first page.
- Unit test for `get_all_items()` mid-pagination error: verify `JellyfinConnectionError` propagates after yielding the first page.

---

### Unit 2: Library Metadata Store (SQLite Repository)

**Purpose:** Create a SQLite-backed repository for library item metadata, following the `SessionStore` pattern, with bulk upsert support and content-hash tracking for incremental sync.

**Functional Requirements:**

- FR-2.1: The system shall add a `library_db_path: str = "data/library.db"` field to `Settings` in `backend/app/config.py`.
- FR-2.2: The system shall add a `jellyfin_api_key: str | None = None` field to `Settings` in `backend/app/config.py`. This enables background sync when set. The field shall be loaded from the `JELLYFIN_API_KEY` environment variable.
- FR-2.3: The system shall create a new module `backend/app/library/store.py` containing a `LibraryStore` class with the same structural pattern as `SessionStore`:
  - Constructor: `__init__(self, db_path: str)`.
  - `async def init(self) -> None` — opens the aiosqlite connection, enables WAL mode, enables `PRAGMA foreign_keys = ON`, and creates the schema.
  - `async def close(self) -> None` — closes the connection.
  - `_conn` property that raises `RuntimeError` if not initialized.
- FR-2.4: The `init()` method shall create the `library_items` table with the following schema:
  ```sql
  CREATE TABLE IF NOT EXISTS library_items (
      jellyfin_id       TEXT PRIMARY KEY,
      title             TEXT NOT NULL,
      overview          TEXT,
      production_year   INTEGER,
      genres            TEXT NOT NULL DEFAULT '[]',    -- JSON array of strings
      tags              TEXT NOT NULL DEFAULT '[]',    -- JSON array of strings
      studios           TEXT NOT NULL DEFAULT '[]',    -- JSON array of strings
      community_rating  REAL,
      people            TEXT NOT NULL DEFAULT '[]',    -- JSON array of strings (cast names only)
      content_hash      TEXT NOT NULL,                 -- SHA-256 hex digest
      synced_at         INTEGER NOT NULL               -- Unix epoch seconds
  );
  CREATE INDEX IF NOT EXISTS idx_library_items_content_hash ON library_items(content_hash);
  CREATE INDEX IF NOT EXISTS idx_library_items_synced_at ON library_items(synced_at);
  ```
- FR-2.5: The `people` column shall store a JSON array of actor name strings only — e.g., `["Tom Hanks", "Robin Wright"]`. The store's upsert logic shall filter the raw Jellyfin `People` array to entries where `Type == "Actor"` and extract only the `Name` field.
- FR-2.6: The system shall create a `LibraryStoreProtocol` in `backend/app/library/models.py` (or a shared location), following the `SessionStoreProtocol` pattern:
  ```python
  class LibraryStoreProtocol(Protocol):
      async def init(self) -> None: ...
      async def close(self) -> None: ...
      async def upsert_many(self, items: list[LibraryItemRow]) -> UpsertResult: ...
      async def get(self, jellyfin_id: str) -> LibraryItemRow | None: ...
      async def get_many(self, ids: list[str]) -> list[LibraryItemRow]: ...
      async def get_all_hashes(self) -> dict[str, str]: ...
      async def count(self) -> int: ...
  ```
- FR-2.7: The system shall define a `LibraryItemRow` dataclass in `backend/app/library/models.py`:
  ```python
  @dataclass(frozen=True, slots=True)
  class LibraryItemRow:
      jellyfin_id: str
      title: str
      overview: str | None
      production_year: int | None
      genres: list[str]
      tags: list[str]
      studios: list[str]
      community_rating: float | None
      people: list[str]       # Actor names only
      content_hash: str       # SHA-256 hex digest
      synced_at: int          # Unix epoch seconds
  ```
- FR-2.8: The system shall define an `UpsertResult` dataclass:
  ```python
  @dataclass(frozen=True, slots=True)
  class UpsertResult:
      created: int
      updated: int
      unchanged: int
  ```
- FR-2.9: The `LibraryStore` shall implement `async def upsert_many(self, items: list[LibraryItemRow]) -> UpsertResult` that:
  1. Wraps the entire batch in a single transaction.
  2. For each item, executes `INSERT INTO library_items (...) VALUES (...) ON CONFLICT(jellyfin_id) DO UPDATE SET ...` — never `INSERT OR REPLACE` (which deletes and re-inserts, losing any future foreign key references).
  3. The `ON CONFLICT ... DO UPDATE` clause shall update all columns except `jellyfin_id`.
  4. Tracks created/updated/unchanged counts by comparing `content_hash` before and after (fetch existing hashes in bulk before the upsert, compare to determine which items are new, changed, or unchanged).
  5. JSON array fields (`genres`, `tags`, `studios`, `people`) are serialized to JSON strings via `json.dumps()` before storage and deserialized via `json.loads()` on read.
- FR-2.10: The `LibraryStore` shall implement `async def get(self, jellyfin_id: str) -> LibraryItemRow | None` — fetch a single item by primary key.
- FR-2.11: The `LibraryStore` shall implement `async def get_many(self, ids: list[str]) -> list[LibraryItemRow]` — fetch multiple items by a list of Jellyfin IDs. This supports the search endpoint (issue #98) which needs to hydrate vector search results with metadata. Use a single query with `WHERE jellyfin_id IN (?, ?, ...)` parameterization (not string interpolation). Return items in no guaranteed order.
- FR-2.12: The `LibraryStore` shall implement `async def get_all_hashes(self) -> dict[str, str]` — return a `{jellyfin_id: content_hash}` mapping for all items. This allows the sync orchestrator to diff against incoming items without loading full rows.
- FR-2.13: The `LibraryStore` shall implement `async def count(self) -> int` — return the total number of items in the store.
- FR-2.14: The content hash for each item shall be computed as `hashlib.sha256(composite_text.encode()).hexdigest()` where `composite_text` is the output of the text builder from Spec 07 (`app/ollama/text_builder.py`). If the text builder module does not yet exist at implementation time, use a placeholder function in `backend/app/library/hashing.py` that builds a deterministic string from the item's fields (title, overview, genres, tags, studios, people, production year, community rating) and hashes it. The placeholder must be clearly marked with a `# TODO: Replace with text_builder from Spec 07` comment, and the function signature must accept a `LibraryItemRow` and return a `str` (the hex digest).
- FR-2.15: All Jellyfin API response data shall pass through Pydantic validation (the extended `LibraryItem` model from Unit 1) before being converted to `LibraryItemRow` for storage. Malformed items that fail Pydantic validation shall be logged at WARNING (item ID only, no metadata) and skipped — they shall not prevent other items from being stored.

**Proof Artifacts:**

- Unit tests for `LibraryStore.init()`: verify table and indexes are created, verify WAL mode is enabled, verify `PRAGMA foreign_keys` is ON.
- Unit tests for `upsert_many()`: insert 3 new items and verify `UpsertResult(created=3, updated=0, unchanged=0)`; upsert the same 3 items with same content hash and verify `UpsertResult(created=0, updated=0, unchanged=3)`; change one item's content hash and verify `UpsertResult(created=0, updated=1, unchanged=2)`.
- Unit tests for `get()`: fetch an existing item, verify all fields round-trip correctly (including JSON arrays), verify `None` for missing ID.
- Unit tests for `get_many()`: insert 5 items, fetch 3 by ID, verify 3 returned; fetch with non-existent IDs mixed in, verify only existing items returned.
- Unit tests for `get_all_hashes()`: insert items, verify the returned dict maps jellyfin_id to content_hash for all items.
- Unit tests for `count()`: empty store returns 0, after inserting 5 items returns 5.
- Unit test for content hash computation: verify deterministic output, verify different input produces different hash.
- Unit test for people filtering: verify that non-Actor entries from the Jellyfin People array are excluded from the stored `people` list.
- Unit test for Pydantic validation: malformed item data is skipped with a WARNING log, valid items are stored.

---

### Unit 3: App Wiring + Config + Documentation

**Purpose:** Wire the `LibraryStore` into the application lifespan, add the `JELLYFIN_API_KEY` configuration with validation, and update project documentation to reflect the two-database strategy and credential handling.

**Functional Requirements:**

- FR-3.1: The system shall update the lifespan in `backend/app/main.py` to:
  1. Create the `data/` directory for `library.db` if it does not exist (same pattern as session DB).
  2. Initialize `LibraryStore` after `SessionStore` initialization.
  3. Store the `LibraryStore` instance on `app.state.library_store`.
  4. Close the `LibraryStore` before closing the `SessionStore` during shutdown (reverse order of initialization).
- FR-3.2: If `JELLYFIN_API_KEY` is set in the environment, the system shall validate at startup that it is non-empty after stripping whitespace. If it is empty/whitespace-only, log a WARNING and treat it as unset (`None`). The API key shall never be logged at any level.
- FR-3.3: The sync JellyfinClient (used for library sync with `JELLYFIN_API_KEY`) shall be a separate instance from the user-facing JellyfinClient. It shall be created during lifespan startup only if `JELLYFIN_API_KEY` is configured. Both clients share the same `httpx.AsyncClient` for connection pooling but are distinct `JellyfinClient` instances.
- FR-3.4: The system shall update `.env.example` to document the `JELLYFIN_API_KEY` setting:
  ```
  # --- Library Sync ---

  # Jellyfin API key for background library sync (optional).
  # Enables automatic sync without requiring a logged-in user session.
  # Generate in Jellyfin: Dashboard > API Keys > Add.
  # SECURITY WARNING: Treat this like a root password — it grants full
  # access to your Jellyfin server. Never commit to version control.
  # If not set, library sync is triggered only via user session tokens.
  # JELLYFIN_API_KEY=

  # Path to the library metadata SQLite database file
  # LIBRARY_DB_PATH=data/library.db

  # Page size for Jellyfin library sync pagination
  # LIBRARY_SYNC_PAGE_SIZE=200
  ```
- FR-3.5: The system shall update `ARCHITECTURE.md` to:
  1. Document the two-file database strategy under the existing "SQLite-vec" component section: `sessions.db` for auth/session data, `library.db` for item metadata and future vector embeddings.
  2. Add a note under the "Security Model" section distinguishing infrastructure credentials (`JELLYFIN_API_KEY` — operator-configured, server-scoped, enables background sync) from user tokens (per-session, encrypted at rest, never persisted to objects).
- FR-3.6: Logging for library sync operations shall follow these rules:
  - DEBUG: Item metadata (for troubleshooting only).
  - INFO: Sync start, sync complete with counts (`items_synced=N, created=N, updated=N, unchanged=N`).
  - WARNING: Pydantic validation failures (item ID only), partial page failures (page number + HTTP status only).
  - ERROR: Complete sync failure.
  - NEVER: user_id paired with item lists, API key values, token values.
- FR-3.7: The system shall add a `backend/app/library/__init__.py` module file.

**Proof Artifacts:**

- Integration test with real Jellyfin: connect to the test Jellyfin instance, call `get_all_items()` with `item_types=["Movie"]`, verify items are returned with expected fields populated, store them in a `LibraryStore`, verify `count()` matches `total_count` from Jellyfin.
- Unit test for lifespan: verify `LibraryStore.init()` is called after `SessionStore.init()`, verify `LibraryStore.close()` is called before `SessionStore.close()`.
- Unit test for `JELLYFIN_API_KEY` validation: empty/whitespace key treated as `None`, valid key stored in settings.
- Verify `.env.example` contains `JELLYFIN_API_KEY` with security warning.
- Verify `ARCHITECTURE.md` documents the two-database strategy and credential distinction.

## Non-Goals (Out of Scope)

1. **Embedding generation** — Spec 07 covers the Ollama embedding client and text builder. This spec stores the content hash but does not generate embeddings.
2. **Vector storage** — Spec 06 covers the SQLite-vec repository. `library.db` stores metadata only; vector data is a separate concern.
3. **Sync orchestration / scheduling** — This spec provides the client and store primitives. The sync coordinator (cron-like scheduling, progress tracking, cancellation) is a separate concern.
4. **TMDb enrichment** — TMDb metadata is opt-in and handled by a separate module. This spec works with Jellyfin metadata only.
5. **API endpoints for sync** — No REST endpoints are added in this spec. Sync is triggered programmatically (by future orchestration code or integration tests).
6. **Item deletion / library diffing** — This spec handles upserts only. Detecting and removing items that were deleted from Jellyfin is deferred.
7. **Permission filtering** — Per-user permission checks happen at query time (Spec 06 / search), not at sync time. The library store contains all items from the server.

## Design Considerations

### Two-Database Strategy

```
data/
├── sessions.db    # Auth sessions (Spec 03) — encrypted tokens, CSRF, expiry
└── library.db     # Library metadata (this spec) — items, content hashes, future vectors
```

Rationale:
- Different access patterns: sessions are small/frequent; library is large/batch.
- Different backup and migration lifecycles.
- `library.db` will eventually house SQLite-vec extension data; `sessions.db` is plain SQLite.
- Both use WAL mode and aiosqlite.

### Content Hash Strategy

The content hash is a SHA-256 digest of the composite text string — the same string that will be fed to the embedding model. This means:

1. If Jellyfin metadata changes, the hash changes, triggering a re-embed.
2. If the text template changes (Spec 07), all hashes change, triggering a full re-embed. This is intentional — a template change means the semantic representation changed.
3. The hash is computed by the caller before passing items to `upsert_many()`. The store does not compute hashes — it stores them.

If the text builder from Spec 07 is not yet available, a placeholder hashing function provides a deterministic hash from raw fields. When the text builder lands, the placeholder is replaced and a one-time full re-sync is expected.

### Token Handling

```
User-triggered sync:
  Frontend → POST /api/sync (future) → backend uses session token
  Token source: decrypted from session store, passed as parameter
  Token lifetime: request-scoped, never stored on objects

Background sync (if JELLYFIN_API_KEY set):
  Startup/cron → sync coordinator → JellyfinClient.get_all_items(api_key, ...)
  Token source: JELLYFIN_API_KEY from Settings (loaded once at startup)
  Token lifetime: process-scoped, read from settings, never logged
```

Both paths use the same `get_all_items(token, user_id, ...)` signature. The sync JellyfinClient is a separate instance to avoid cross-contamination with user-facing request handling.

### Module Layout

```
backend/app/
├── jellyfin/
│   ├── client.py          # Extended: get_all_items() async iterator
│   └── models.py          # Extended: LibraryItem with Tags, Studios, etc.
├── library/
│   ├── __init__.py
│   ├── models.py          # LibraryItemRow, UpsertResult, LibraryStoreProtocol
│   ├── store.py           # LibraryStore (SQLite repository)
│   └── hashing.py         # Content hash computation (placeholder or text_builder)
├── config.py              # Extended: library_db_path, jellyfin_api_key, library_sync_page_size
└── main.py                # Extended: LibraryStore in lifespan
```

## Repository Standards

- All new code uses `async/await` for I/O (aiosqlite, httpx).
- Type hints on all function signatures. Pydantic models for API response parsing.
- Tests use `pytest` with `pytest-asyncio`. Mark integration tests with `@pytest.mark.integration`.
- Lint with `ruff`. Type-check with `pyright` (basic mode).
- Conventional commits: `feat(library):`, `test(library):`, `fix(library):`, `docs:`.
- No `any` types in Python — use proper types or generics.
- No ad-hoc `os.environ` calls — all config via `Settings` (Pydantic BaseSettings).
- No logging of PII, tokens, or API keys.
- Mock Jellyfin API in unit tests; integration tests use the real Jellyfin instance (`make test-integration`).

## Technical Considerations

- **aiosqlite**: Already a project dependency (used by `SessionStore`). The `LibraryStore` uses the same library and patterns.
- **`INSERT ... ON CONFLICT DO UPDATE`**: This is SQLite's upsert syntax (available since 3.24.0, 2018). It updates in-place without deleting the row, preserving any future foreign key references or rowid-dependent data. Never use `INSERT OR REPLACE` which performs a delete+insert.
- **JSON array storage**: Genres, tags, studios, and people are stored as JSON text columns (`json.dumps()` / `json.loads()`). SQLite's JSON functions could be used for querying, but are not needed for this spec's access patterns (full-row reads).
- **`get_many()` parameterization**: For large ID lists, SQLite has a `SQLITE_MAX_VARIABLE_NUMBER` limit (default 999 in older versions, 32766 in 3.32+). If the ID list exceeds a safe threshold (e.g., 500), chunk into multiple queries. This is a defensive measure for very large search result sets.
- **Async iterator**: `get_all_items()` uses `async for` / `yield` to produce an `AsyncIterator[PaginatedItems]`. This keeps memory usage proportional to a single page, not the entire library.
- **Content hash determinism**: The hash input string must be built deterministically — sorted JSON arrays, consistent field ordering, normalized whitespace. The placeholder hashing function must document its field ordering.
- **Startup order**: `LibraryStore.init()` runs after `SessionStore.init()` because sessions are required for the app to be functional (auth), while library data is supplementary. Shutdown reverses this order.

## Security Considerations

- **`JELLYFIN_API_KEY` is a high-privilege credential**: It grants server-admin-level access to Jellyfin. It must never appear in logs, error messages, or API responses at any log level. The `.env.example` documentation warns operators to treat it like a root password.
- **Token parameter discipline**: Both `get_all_items()` and the sync orchestrator accept tokens as function parameters, never storing them on `self`. This ensures tokens cannot leak via object serialization, logging of object state, or accidental cross-request reuse.
- **Sync client isolation**: The sync `JellyfinClient` instance is separate from the user-facing instance. This prevents a background sync's API key from accidentally being used for a user request or vice versa.
- **No PII in logs**: Item metadata (titles, genres, etc.) is logged at DEBUG only. User IDs are never paired with item lists. Sync results use aggregate counts only at INFO level.
- **Input validation**: All Jellyfin data passes through Pydantic models before storage. This prevents injection of malformed data into the SQLite database. Items that fail validation are skipped and logged (ID only).
- **SQL injection prevention**: All database queries use parameterized queries (`?` placeholders). No string interpolation or f-strings in SQL statements.
- **`PRAGMA foreign_keys = ON`**: Enabled on every connection to enforce referential integrity for any future foreign key constraints.

## Success Metrics

1. `get_all_items()` correctly auto-paginates a library of any size, verified by unit tests with mocked multi-page responses and integration test against real Jellyfin.
2. `LibraryStore.upsert_many()` correctly reports created/updated/unchanged counts, verified by unit tests with sequential upserts of the same and modified data.
3. Content hashes are deterministic — the same item data always produces the same hash, and any field change produces a different hash (verified by unit test).
4. The `people` field stores actor names only — non-actor People entries are filtered out (verified by unit test).
5. `get_many()` returns correct items for a batch of IDs, supporting the search endpoint hydration use case (verified by unit test).
6. The lifespan correctly initializes `LibraryStore` after `SessionStore` and closes in reverse order (verified by unit test).
7. `JELLYFIN_API_KEY` is never logged at any level (verified by log output inspection in tests).
8. Integration test: full cycle — fetch library from real Jellyfin, store in `LibraryStore`, verify `count()` matches Jellyfin's `TotalRecordCount`.
9. `.env.example` and `ARCHITECTURE.md` are updated with the new configuration and architectural context.

## Open Questions

None — all design decisions have been resolved through the Watch Council review process.
