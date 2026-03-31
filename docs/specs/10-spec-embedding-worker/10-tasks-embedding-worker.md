# 10 Tasks - Embedding Worker

## Relevant Files

### Files to Create
- `backend/app/embedding/__init__.py` — Package init, re-exports public API (EmbeddingWorker)
- `backend/app/embedding/worker.py` — `EmbeddingWorker` class: processing loop, retry policy, error classification, template version detection
- `backend/app/embedding/router.py` — Admin embedding status endpoint (`GET /api/admin/embedding/status`)
- `backend/app/embedding/models.py` — Pydantic response models for admin endpoint (`EmbeddingStatusResponse`, `EmbeddingFailedItem`)
- `backend/tests/test_library_store_embedding.py` — Unit tests for new LibraryStore queue methods
- `backend/tests/test_ollama_embed_batch.py` — Unit tests for `embed_batch()` on OllamaEmbeddingClient
- `backend/tests/test_vec_repo_upsert_many.py` — Unit tests for `upsert_many()` on SqliteVecRepository
- `backend/tests/test_embedding_worker.py` — Unit tests for EmbeddingWorker lifecycle, retry, error classification
- `backend/tests/test_template_version.py` — Unit tests for template version detection logic
- `backend/tests/test_embedding_admin.py` — Unit tests for admin embedding status endpoint
- `backend/tests/test_health_embeddings.py` — Unit tests for updated health endpoint embedding fields

### Files to Modify
- `backend/app/library/store.py` — Add `busy_timeout`, `last_attempted_at` migration, update ON CONFLICT clause, add queue management methods
- `backend/app/ollama/client.py` — Add `embed_batch()` method
- `backend/app/vectors/repository.py` — Add `upsert_many()`, `get_template_version()`, `set_template_version()`
- `backend/app/config.py` — Add embedding worker settings with validation
- `backend/app/models.py` — Update `EmbeddingsStatus` model with `failed` and `worker_status` fields
- `backend/app/main.py` — Lifespan wiring: create Event, wire worker, update health endpoint, mount admin router, shutdown ordering
- `backend/app/sync/engine.py` — Set `asyncio.Event` after `run_sync()` completes (one-line addition)
- `.env.example` — Document new embedding settings

### Reference Files (read-only context for implementation)
- `backend/app/sync/router.py` — Pattern reference for admin endpoint with `require_admin` dependency
- `backend/app/sync/dependencies.py` — Pattern reference for `require_admin` auth check
- `backend/app/sync/models.py` — Pattern reference for admin response Pydantic models
- `backend/app/ollama/errors.py` — Error hierarchy: `OllamaError` → `OllamaConnectionError`, `OllamaTimeoutError`, `OllamaModelError`
- `backend/app/ollama/models.py` — `EmbeddingResult` model with dimension validator
- `backend/app/library/text_builder.py` — `TEMPLATE_VERSION` constant, `build_composite_text()` function
- `backend/app/library/models.py` — `LibraryItemRow` model
- `backend/tests/conftest.py` — Shared test fixtures, `make_test_settings()`, env setup pattern
- `backend/tests/test_ollama_client.py` — Pattern reference for httpx mocking and Ollama client tests
- `backend/tests/test_vec_repository.py` — Pattern reference for vec repo tests with `tmp_path` fixtures
- `backend/tests/test_library_store.py` — Pattern reference for LibraryStore tests with `tmp_path` fixtures
- `backend/tests/test_sync_engine.py` — Pattern reference for mocking dependencies in async tests

### Notes

- Unit tests are placed in `backend/tests/test_*.py` (flat, not nested by module)
- Integration tests are in `backend/tests/integration/test_*.py` with `@pytest.mark.ollama_integration`
- Tests use `async def` without explicit `@pytest.mark.asyncio` (configured globally)
- Async fixtures use `async def` with `AsyncIterator` type hint and `yield`
- Temporary databases use pytest's `tmp_path` fixture
- Mock HTTP clients use `AsyncMock(spec=httpx.AsyncClient)` with `httpx.Response()` return values
- Test classes group related tests; no inheritance from base test classes
- Factory helpers (`_make_item()`, `_make_embedding()`) at module scope build deterministic test data
- Run tests: `make test` (unit), `make test-integration` (integration)
- Lint: `make lint` (ruff)

---

## Tasks

### [x] 1.0 Store Methods, Schema Migration, and Settings

Establish the data-layer foundation that all subsequent tasks depend on. Add `busy_timeout` to LibraryStore (prerequisite fix from council review), migrate `embedding_queue` with `last_attempted_at` column, update the ON CONFLICT clause in `enqueue_for_embedding()` to reset `last_attempted_at=NULL`, add new queue management methods to LibraryStore, and add new Settings fields with validation.

#### 1.0 Proof Artifact(s)

- [test]: `backend/tests/test_library_store_embedding.py` — unit tests for all new queue methods: `get_retryable_items` respects cooldown and max retries, `claim_batch` transitions `pending` → `processing`, `mark_embedded` deletes the row, `mark_failed_permanent` sets `failed` status, `reset_stale_processing` resets `processing` → `pending`
- [test]: `backend/tests/test_library_store_embedding.py` — ON CONFLICT re-enqueue resets `last_attempted_at` to NULL
- [test]: `backend/tests/test_config.py` — new settings fields load from environment with correct defaults and batch size validation rejects values > 50
- [verify]: `PRAGMA busy_timeout` returns 5000 on LibraryStore connection
- [verify]: `make lint` passes

#### 1.0 Tasks

**LibraryStore prerequisite fix**
- [x] 1.1 Add `await self._db.execute("PRAGMA busy_timeout=5000")` to `LibraryStore.init()` in `store.py`, immediately after the WAL and foreign_keys pragmas (line ~107). This prevents `SQLITE_BUSY` when the embedding worker and sync engine write concurrently.

**Schema migration**
- [x] 1.2 Add `last_attempted_at` column migration to `LibraryStore.init()` using the existing `PRAGMA table_info` pattern (see lines 113-119 for the `deleted_at` migration example). Check if `last_attempted_at` exists in `embedding_queue`; if not, `ALTER TABLE embedding_queue ADD COLUMN last_attempted_at INTEGER`. The column is nullable with no default — existing rows get NULL, which is correct.

**ON CONFLICT update**
- [x] 1.3 Update the ON CONFLICT clause in `enqueue_for_embedding()` (line ~421) to also reset `last_attempted_at=NULL`. Change from `status='pending', enqueued_at=excluded.enqueued_at, retry_count=0, error_message=NULL` to include `last_attempted_at=NULL`. Without this, re-enqueued items carry stale timestamps that make cooldown logic skip them incorrectly.

**New queue management methods on LibraryStore**
- [x] 1.4 Add `get_retryable_items(cooldown_seconds: int, max_retries: int, batch_size: int) -> list[tuple[str, int]]` method. Returns `(jellyfin_id, retry_count)` pairs for items that are: status='pending' AND (last_attempted_at IS NULL OR last_attempted_at < now - cooldown_seconds) AND retry_count <= max_retries. ORDER BY enqueued_at ASC, LIMIT batch_size. Use a single atomic query.
- [x] 1.5 Add `claim_batch(ids: list[str]) -> int` method. Single atomic `UPDATE embedding_queue SET status='processing', last_attempted_at=? WHERE jellyfin_id IN (?) AND status='pending'`. Returns number of rows affected. This is the concurrency guard — no SELECT-then-UPDATE.
- [x] 1.6 Add `mark_embedded(jellyfin_id: str) -> None` method. `DELETE FROM embedding_queue WHERE jellyfin_id = ?`.
- [x] 1.7 Add `mark_embedded_many(ids: list[str]) -> int` method. Batch delete with chunking at `_BATCH_SIZE`, wrapped in a transaction. Returns count deleted.
- [x] 1.8 Add `mark_attempt(jellyfin_id: str, error_message: str) -> None` method. `UPDATE embedding_queue SET status='pending', retry_count=retry_count+1, error_message=?, last_attempted_at=? WHERE jellyfin_id=?`. This returns a transient failure to the queue for retry.
- [x] 1.9 Add `mark_failed_permanent(jellyfin_id: str, reason: str) -> None` method. `UPDATE embedding_queue SET status='failed', error_message=?, last_attempted_at=? WHERE jellyfin_id=?`.
- [x] 1.10 Add `reset_stale_processing() -> int` method. `UPDATE embedding_queue SET status='pending' WHERE status='processing'`. Returns number of rows reset. Called at startup for crash recovery.
- [x] 1.11 Add `get_failed_items() -> list[dict]` method. Returns `[{jellyfin_id, error_message, retry_count, last_attempted_at}]` for all items with status='failed'. Used by the admin endpoint.
- [x] 1.12 Add `get_queue_counts() -> dict[str, int]` method. Returns `{pending: N, processing: N, failed: N}` from a single GROUP BY query. Used by health and admin endpoints.

**Settings**
- [x] 1.13 Add the following fields to `Settings` in `config.py`:
  - `embedding_batch_size: int = 10` — items per processing cycle
  - `embedding_worker_interval_seconds: int = 300` — poll interval
  - `embedding_max_retries: int = 3` — max transient retries before marking failed
  - `embedding_cooldown_seconds: int = 300` — minimum time between retry attempts
- [x] 1.14 Add a `@model_validator` for `embedding_batch_size` that rejects values < 1 or > 50 with a clear error message.

**Tests**
- [x] 1.15 Create `backend/tests/test_library_store_embedding.py` with async fixture creating a LibraryStore in `tmp_path`. Write tests for:
  - `get_retryable_items` returns pending items respecting cooldown and max retries
  - `get_retryable_items` skips items whose `last_attempted_at` is within cooldown window
  - `get_retryable_items` skips items where retry_count > max_retries
  - `get_retryable_items` respects batch_size limit
  - `claim_batch` transitions status from `pending` to `processing`
  - `claim_batch` returns 0 for items not in `pending` status
  - `mark_embedded` deletes the queue row
  - `mark_embedded_many` deletes multiple rows atomically
  - `mark_attempt` increments retry_count and sets error_message
  - `mark_failed_permanent` sets status to `failed` with reason
  - `reset_stale_processing` resets `processing` items to `pending`
  - `reset_stale_processing` does not affect `pending` or `failed` items
  - `get_failed_items` returns correct failure details
  - `get_queue_counts` returns correct breakdown
  - `enqueue_for_embedding` ON CONFLICT resets `last_attempted_at` to NULL
  - Verify `busy_timeout` pragma is set on the connection
- [x] 1.16 Add tests to `backend/tests/test_config.py` for new settings: default values, environment override, batch_size validator rejects 0 and 51

**Environment documentation**
- [x] 1.17 Add `EMBEDDING_BATCH_SIZE`, `EMBEDDING_WORKER_INTERVAL_SECONDS`, `EMBEDDING_MAX_RETRIES`, `EMBEDDING_COOLDOWN_SECONDS` to `.env.example` with comments explaining each

---

### [x] 2.0 Ollama Batch Embedding API + Vector Batch Upsert

Extend `OllamaEmbeddingClient` with `embed_batch()` and `SqliteVecRepository` with `upsert_many()`. These are the two new methods on existing classes that the worker's processing loop will call.

#### 2.0 Proof Artifact(s)

- [test]: `backend/tests/test_ollama_embed_batch.py` — unit tests for `embed_batch()`: happy path with multiple texts, positional mapping of input→output, per-vector dimension validation, empty input returns empty list, Ollama returning fewer vectors than inputs raises `OllamaError`
- [test]: `backend/tests/test_vec_repo_upsert_many.py` — unit tests for `upsert_many()`: batch of N items stored atomically, mid-batch failure rolls back entire transaction, empty input is a no-op, duplicate IDs overwrite existing vectors
- [verify]: `make lint` passes

#### 2.0 Tasks

**`embed_batch()` on OllamaEmbeddingClient**
- [x] 2.1 Add `embed_batch(self, texts: list[str]) -> list[EmbeddingResult]` to `OllamaEmbeddingClient` in `client.py`. POSTs to `{base_url}/api/embed` with `{"model": self._embed_model, "input": texts}`. Ollama returns `{"embeddings": [[vec1], [vec2], ...]}`. Map each vector to an `EmbeddingResult` with dimension validation. Log total elapsed_ms and count.
- [x] 2.2 Handle edge cases in `embed_batch()`:
  - Empty `texts` list → return `[]` immediately (no HTTP call)
  - Ollama returns fewer vectors than input texts → raise `OllamaError` with sanitized message
  - Same error wrapping as `embed()`: `httpx.TimeoutException` → `OllamaTimeoutError`, `httpx.TransportError` → `OllamaConnectionError`, 404 → `OllamaModelError`, other 4xx/5xx → `OllamaError`

**`upsert_many()` on SqliteVecRepository**
- [x] 2.3 Add `upsert_many(self, items: list[tuple[str, list[float], str]]) -> None` to `SqliteVecRepository` in `repository.py`. Each tuple is `(jellyfin_id, embedding, content_hash)`. Wraps all DELETE+INSERT pairs in a single explicit transaction (BEGIN, loop of DELETE+INSERT, COMMIT). Rolls back on any exception. Follows the existing single-item `upsert()` pattern at lines 173-197.
- [x] 2.4 Handle edge cases in `upsert_many()`:
  - Empty items list → return immediately (no transaction)
  - Serialize vectors with `_serialize_f32()` (existing helper)
  - Set `embedded_at = int(time.time())` and `embedding_status = COMPLETE` for all items

**Tests**
- [x] 2.5 Create `backend/tests/test_ollama_embed_batch.py` following the pattern in `test_ollama_client.py`. Use `AsyncMock(spec=httpx.AsyncClient)` for the HTTP client. Write tests for:
  - `embed_batch` with 3 texts returns 3 `EmbeddingResult` objects with correct dimensions
  - Positional mapping: first text maps to first vector, second to second, etc.
  - Per-vector dimension validation catches mismatched dimensions
  - Empty input returns empty list without HTTP call
  - Ollama returning fewer vectors than texts raises `OllamaError`
  - Timeout → `OllamaTimeoutError`
  - Connection error → `OllamaConnectionError`
  - 404 → `OllamaModelError`
  - Non-2xx → `OllamaError`
- [x] 2.6 Create `backend/tests/test_vec_repo_upsert_many.py` following the pattern in `test_vec_repository.py`. Use `tmp_path` fixture with real SQLite-vec. Mark with `pytestmark = pytest.mark.requires_sqlite_vec`. Write tests for:
  - Batch upsert of 5 items: all stored, `count()` returns 5
  - Duplicate IDs in batch: last write wins (no error)
  - Upsert overwrites existing vectors for same `jellyfin_id`
  - Empty input is a no-op
  - Mid-batch failure (corrupt vector data) rolls back entire transaction — count remains at pre-upsert level
  - Verify `content_hash` and `embedded_at` are set correctly on each record

---

### [x] 3.0 Embedding Worker Core with Retry Policy

Build the `EmbeddingWorker` class that combines the processing loop and error handling. The worker: checks Ollama health → claims a batch → builds composite text → calls `embed_batch()` → stores vectors via `upsert_many()` → deletes from queue on success. Error classification splits failures into transient (retry with cooldown) and permanent (fail immediately). Batch failures fall back to individual item processing.

#### 3.0 Proof Artifact(s)

- [test]: `backend/tests/test_embedding_worker.py` — unit tests covering: full claim→embed→store→delete lifecycle, Ollama health check skips cycle when unhealthy, concurrent run prevention via Lock, batch fallback to individual items on batch failure, transient error increments retry_count and returns to pending, permanent error (OllamaModelError) marks failed immediately, cooldown skips recently-attempted items, max retries exhaustion marks failed, error messages sanitized (no raw exception strings)
- [test]: `backend/tests/test_embedding_worker.py` — startup `reset_stale_processing` is called before first cycle
- [verify]: `make lint` passes
- [verify]: `make test` — all unit tests pass

#### 3.0 Tasks

**Package scaffolding**
- [x] 3.1 Create `backend/app/embedding/__init__.py` with `from app.embedding.worker import EmbeddingWorker` re-export and `__all__ = ["EmbeddingWorker"]`

**EmbeddingWorker class**
- [x] 3.2 Create `backend/app/embedding/worker.py`. Define `EmbeddingWorker` class with `__init__` accepting: `library_store: LibraryStore`, `vec_repo: SqliteVecRepository`, `ollama_client: OllamaEmbeddingClient`, `settings: Settings`, `sync_event: asyncio.Event`. Store as private attributes. Create `asyncio.Lock` as `_lock`. Initialize state tracking: `_status: str = "idle"`, `_last_batch_at: int | None = None`, `_last_error: str | None = None`.

**Processing cycle**
- [x] 3.3 Implement `async def process_cycle(self) -> None` — the single-cycle method:
  1. Health check: call `self._ollama_client.health()`. If unhealthy, log warning and return early. Do NOT modify any queue states.
  2. Fetch retryable items: call `self._library_store.get_retryable_items(cooldown, max_retries, batch_size)`. If empty, return.
  3. Claim batch: call `self._library_store.claim_batch(ids)`. If 0 claimed, return.
  4. For each claimed item: fetch `LibraryItemRow` from library_store, call `build_composite_text()` to get text.
  5. Attempt `embed_batch(texts)`. On success: call `vec_repo.upsert_many(results)`, then `library_store.mark_embedded_many(ids)`.
  6. On batch failure: fall back to individual processing (sub-task 3.5).
  7. Update `_last_batch_at` timestamp. Update `_status`.

- [x] 3.4 Implement individual item processing within `process_cycle`: for each item in the claimed batch, call `ollama_client.embed(text)` individually. On success: `vec_repo.upsert(id, vector, hash)` then `library_store.mark_embedded(id)`. On error: classify and handle per sub-task 3.5.

**Error classification**
- [x] 3.5 Implement error classification in the individual item processing path:
  - `OllamaModelError` → call `mark_failed_permanent(id, "OllamaModelError: model not found — run 'ollama pull nomic-embed-text'")`. This is a permanent error.
  - `OllamaTimeoutError`, `OllamaConnectionError`, `OllamaError` → transient. Check if `retry_count >= max_retries`: if yes, call `mark_failed_permanent(id, sanitized_message)`; if no, call `mark_attempt(id, sanitized_message)`.
  - Unexpected `Exception` → treat as transient, sanitize with `f"{type(exc).__name__}: {type(exc).__doc__ or 'embedding failed'}"`. Never `str(exc)`.
  - Log each error with structured key=value pairs. Never log raw Ollama response bodies.

**Batch fallback**
- [x] 3.6 Implement batch fallback in `process_cycle`: when `embed_batch()` raises any exception, log the batch failure, then process each item individually via the path in 3.4. This isolates which specific items are failing.

**Run loop**
- [x] 3.7 Implement `async def run(self) -> None` — the long-running asyncio loop:
  1. Log worker startup.
  2. Loop forever:
     a. Wait for either `sync_event` to be set OR `asyncio.sleep(interval)` — use `asyncio.wait()` with `return_when=FIRST_COMPLETED` on wrapped awaitables.
     b. Clear the event if it was set.
     c. Attempt to acquire `_lock` with a tiny timeout (1s). If already locked, log and skip.
     d. Inside lock: set `_status = "processing"`, call `process_cycle()`, set `_status = "idle"`.
     e. Catch `asyncio.CancelledError` — re-raise for clean shutdown.
     f. Catch all other exceptions — log, set `_last_error`, continue loop.

**Startup reset**
- [x] 3.8 Implement `async def startup(self) -> None` — called once in lifespan before the run loop task is created. Calls `self._library_store.reset_stale_processing()` and logs the count of items reset.

**Tests**
- [x] 3.9 Create `backend/tests/test_embedding_worker.py`. Mock all dependencies (`LibraryStore`, `SqliteVecRepository`, `OllamaEmbeddingClient`) using `AsyncMock`. Write tests for:
  - **Happy path**: `process_cycle` with 3 pending items → claims, embeds batch, upserts vectors, deletes from queue
  - **Ollama unhealthy**: `health()` returns False → cycle skipped, no queue modifications
  - **Empty queue**: `get_retryable_items` returns `[]` → cycle returns early
  - **Batch failure → individual fallback**: `embed_batch` raises `OllamaError` → each item processed individually
  - **Transient error (individual)**: `embed()` raises `OllamaTimeoutError` → `mark_attempt` called with retry_count < max
  - **Permanent error**: `embed()` raises `OllamaModelError` → `mark_failed_permanent` called immediately
  - **Max retries exceeded**: item with retry_count >= max_retries on transient error → `mark_failed_permanent`
  - **Error message sanitization**: unexpected `Exception("secret path /foo/bar")` → stored message uses `type(exc).__name__: type(exc).__doc__`, not the raw string
  - **Lock prevents concurrent runs**: second `process_cycle` call while first is running → skipped
  - **Startup reset**: `startup()` calls `reset_stale_processing()`

---

### [x] 4.0 Template Version Detection

Implement the startup version check that detects stale embeddings when `TEMPLATE_VERSION` changes. On worker initialization, read `template_version` from `_vec_meta`. If stored < current, re-enqueue all non-tombstoned items and update the meta value.

#### 4.0 Proof Artifact(s)

- [test]: `backend/tests/test_template_version.py` — unit tests for: absent version triggers full enqueue + writes current version, matching version enqueues nothing, stale version (stored < current) triggers full enqueue + updates meta, downgrade (stored > current) is a no-op, idempotency (two checks with same version don't re-enqueue)
- [verify]: `make lint` passes

#### 4.0 Tasks

**SqliteVecRepository methods**
- [x] 4.1 Add `async def get_template_version(self) -> int | None` to `SqliteVecRepository`. Query `SELECT value FROM _vec_meta WHERE key = 'template_version'`. Return `int(value)` if found, `None` if absent.
- [x] 4.2 Add `async def set_template_version(self, version: int) -> None` to `SqliteVecRepository`. Use `INSERT INTO _vec_meta (key, value) VALUES ('template_version', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value`. Commit.

**Worker integration**
- [x] 4.3 Add `async def check_template_version(self) -> None` to `EmbeddingWorker`. Logic:
  1. Read stored version via `vec_repo.get_template_version()`. Treat `None` as 0.
  2. Import `TEMPLATE_VERSION` from `app.library.text_builder`.
  3. If stored >= current: log "template version current" and return (handles both match and downgrade).
  4. If stored < current: log "template version stale", get all non-tombstoned item IDs from `library_store.get_all_ids()`, call `library_store.enqueue_for_embedding(list(ids))`, call `vec_repo.set_template_version(TEMPLATE_VERSION)`. Log count of items re-enqueued.
- [x] 4.4 Update `EmbeddingWorker.startup()` (from 3.8) to call `check_template_version()` after `reset_stale_processing()`.

**Tests**
- [x] 4.5 Create `backend/tests/test_template_version.py`. Use mocked `SqliteVecRepository` and `LibraryStore`. Write tests for:
  - Absent version (returns None) → `enqueue_for_embedding` called with all IDs, `set_template_version` called with current version
  - Matching version (stored == current) → no enqueue, no meta update
  - Stale version (stored < current) → full enqueue + meta update
  - Downgrade (stored > current) → no enqueue, no meta update (no-op)
  - Idempotency: call `check_template_version` twice with stored == current → `enqueue_for_embedding` not called on either invocation
  - ON CONFLICT deduplication: items already pending are not duplicated (verified by checking `enqueue_for_embedding` is called once with correct IDs — the ON CONFLICT behavior is tested in 1.0)

---

### [ ] 5.0 Observability Endpoints and Lifespan Wiring

Wire the embedding worker into the FastAPI application. Update the health endpoint, add the admin status endpoint, and connect the worker to the lifespan with correct startup/shutdown ordering.

#### 5.0 Proof Artifact(s)

- [test]: `backend/tests/test_health_embeddings.py` — `/health` returns real `pending`, `failed`, `total` counts and `worker_status`
- [test]: `backend/tests/test_embedding_admin.py` — `GET /api/admin/embedding/status` returns queue breakdown (pending/processing/failed counts), worker state, last batch timestamp, failed items list with error details; requires admin auth (401/403 on non-admin)
- [test]: Lifespan creates worker task and cancels it on shutdown
- [verify]: `make test` — full test suite passes
- [verify]: `make lint` passes
- [screenshot]: Health endpoint JSON showing non-zero embedding counts (integration)

#### 5.0 Tasks

**Response models**
- [ ] 5.1 Update `EmbeddingsStatus` in `backend/app/models.py`: add `failed: int = 0` and `worker_status: str = "idle"` fields. Existing callers that construct `EmbeddingsStatus(total=N, pending=0)` continue to work because new fields have defaults.
- [ ] 5.2 Create `backend/app/embedding/models.py` with Pydantic response models:
  - `EmbeddingFailedItem(jellyfin_id: str, error_message: str | None, retry_count: int, last_attempted_at: int | None)`
  - `EmbeddingStatusResponse(status: str, pending: int, processing: int, failed: int, total_vectors: int, last_batch_at: int | None, last_error: str | None, batch_size: int, failed_items: list[EmbeddingFailedItem])`

**Admin router**
- [ ] 5.3 Create `backend/app/embedding/router.py` with `APIRouter(prefix="/api/admin/embedding", tags=["admin"])`. Add `GET /status` endpoint using `Depends(require_admin)` (import from `app.sync.dependencies`). Read worker state from `request.app.state.embedding_worker`, queue counts from `request.app.state.library_store.get_queue_counts()`, failed items from `request.app.state.library_store.get_failed_items()`, total vectors from `request.app.state.vec_repo.count()`. Return `EmbeddingStatusResponse`.

**Health endpoint update**
- [ ] 5.4 Update the `/health` endpoint in `main.py` to:
  - Read queue counts via `lib_store.get_queue_counts()` (add to the existing `asyncio.gather` on line ~305)
  - Read `worker_status` from `app.state.embedding_worker.status` (with a try/except fallback to "idle" if worker not initialized)
  - Replace the hardcoded `pending=0` on line ~324 with real counts: `EmbeddingsStatus(total=total, pending=queue_counts["pending"], failed=queue_counts["failed"], worker_status=worker_status)`

**Lifespan wiring**
- [ ] 5.5 In `main.py` lifespan, after the sync engine creation (~line 159), add:
  1. Create `embedding_event = asyncio.Event()`
  2. Create `EmbeddingWorker(library_store, vec_repo, ollama_client, settings, embedding_event)`
  3. Call `await embedding_worker.startup()` (runs `reset_stale_processing` + `check_template_version`)
  4. Register `app.state.embedding_worker = embedding_worker`
  5. Create the worker background task: `embedding_task = asyncio.create_task(embedding_worker.run())`
  6. Log: `_logger.info("embedding worker started — interval=%ds batch_size=%d", settings.embedding_worker_interval_seconds, settings.embedding_batch_size)`

- [ ] 5.6 Modify `SyncEngine.run_sync()` in `sync/engine.py`: accept an optional `embedding_event: asyncio.Event | None = None` parameter (or store on `__init__`). After `save_sync_run(result)` on line ~295, call `if self._embedding_event: self._embedding_event.set()`. This is the trigger that wakes the worker after sync completes. Update SyncEngine `__init__` to accept and store the event.

- [ ] 5.7 Update the SyncEngine creation in `main.py` lifespan to pass the `embedding_event` to `SyncEngine.__init__`.

- [ ] 5.8 Update shutdown ordering in `main.py` lifespan (after yield). Add embedding task cancellation BEFORE sync task cancellation (LIFO — embedding depends on sync):
  ```
  # Shutdown order: embedding → sync → cleanup → ollama → vec → lib → sessions
  if embedding_task is not None:
      embedding_task.cancel()
      with contextlib.suppress(asyncio.CancelledError):
          await embedding_task
  ```

- [ ] 5.9 Mount the embedding admin router in the lifespan: `app.include_router(embedding_router)` alongside the existing `app.include_router(sync_router)`.

**Environment documentation**
- [ ] 5.10 Update `.env.example` with all new embedding worker settings, with comments:
  ```
  # Embedding Worker
  # EMBEDDING_BATCH_SIZE=10          # Items per processing cycle (1-50)
  # EMBEDDING_WORKER_INTERVAL_SECONDS=300  # Poll interval in seconds
  # EMBEDDING_MAX_RETRIES=3          # Max transient retries before marking failed
  # EMBEDDING_COOLDOWN_SECONDS=300   # Min seconds between retry attempts
  ```

**Tests**
- [ ] 5.11 Create `backend/tests/test_health_embeddings.py`. Use the test client pattern from `conftest.py`. Mock `LibraryStore.get_queue_counts()` to return known values. Verify `/health` response includes: `embeddings.pending`, `embeddings.failed`, `embeddings.total`, `embeddings.worker_status`.
- [ ] 5.12 Create `backend/tests/test_embedding_admin.py`. Follow the pattern in existing sync admin tests. Write tests for:
  - `GET /api/admin/embedding/status` with admin session → 200 with correct response shape
  - `GET /api/admin/embedding/status` without session → 401
  - `GET /api/admin/embedding/status` with non-admin session → 403
  - Response includes `pending`, `processing`, `failed` counts, `status`, `last_batch_at`, `failed_items` list
- [ ] 5.13 Write a lifespan test verifying: worker task is created, worker startup is called (reset + template version check), worker task is cancelled on shutdown. This can be a focused test or added to existing lifespan tests if they exist.
