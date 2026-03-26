# 07 Tasks - Ollama Embedding Client

## Relevant Files

### Files to Create

| File | Purpose |
|------|---------|
| `backend/app/ollama/__init__.py` | Package init with `__all__` re-exports (mirrors `jellyfin/__init__.py`) |
| `backend/app/ollama/errors.py` | Error hierarchy: `OllamaError` > `OllamaConnectionError`, `OllamaTimeoutError`, `OllamaModelError` |
| `backend/app/ollama/models.py` | `EmbeddingResult`, `EmbeddingSource` Pydantic models |
| `backend/app/ollama/client.py` | `OllamaEmbeddingClient` with `embed()` and `health()` methods |
| `backend/app/ollama/text_builder.py` | `TEMPLATE_VERSION`, `CompositeTextResult`, `build_composite_text()` |
| `backend/tests/test_ollama_client.py` | Unit tests for `OllamaEmbeddingClient` (mocked httpx) |
| `backend/tests/test_text_builder.py` | Unit + snapshot tests for `build_composite_text()` |

### Files to Modify

| File | Change |
|------|--------|
| `backend/app/config.py` | Add `ollama_embed_timeout` and `ollama_health_timeout` fields to `Settings` |
| `backend/app/main.py` | Wire Ollama httpx client + `OllamaEmbeddingClient` into lifespan; update `/health` endpoint |
| `.env.example` | Add `OLLAMA_EMBED_TIMEOUT` and `OLLAMA_HEALTH_TIMEOUT` entries (commented out) |
| `backend/tests/test_main.py` | Add tests for lifespan Ollama wiring and `/health` integration with `OllamaEmbeddingClient.health()` |

### Reference Files (read-only context)

| File | Why |
|------|-----|
| `backend/app/jellyfin/client.py` | HTTP client pattern to mirror (constructor injection, `_request` helper, error mapping) |
| `backend/app/jellyfin/errors.py` | Error hierarchy pattern to mirror |
| `backend/app/jellyfin/models.py` | `LibraryItem` model consumed by text builder; Pydantic model patterns |
| `backend/app/jellyfin/__init__.py` | `__all__` re-export pattern to mirror |
| `backend/tests/test_jellyfin_client.py` | Test patterns: mocked `httpx.AsyncClient`, `httpx.Response` construction, error assertions |
| `backend/app/models.py` | `HealthResponse` model showing current `/health` response shape |

---

## Tasks

### [x] 1.0 Ollama Embedding Client + Error Hierarchy

Create the `backend/app/ollama/` package with error hierarchy, Pydantic models, and the async embedding client. Mirrors the `backend/app/jellyfin/` package layout: `errors.py` defines `OllamaError > OllamaConnectionError | OllamaTimeoutError | OllamaModelError`; `models.py` defines `EmbeddingResult` and `EmbeddingSource` (StrEnum); `client.py` defines `OllamaEmbeddingClient` with constructor-injected `httpx.AsyncClient`, `embed()` method calling `/api/embed`, and `health()` method with per-request timeout override. Add `ollama_embed_timeout` and `ollama_health_timeout` fields to `Settings` in `config.py`. Package `__init__.py` provides clean `__all__` re-exports.

#### 1.0 Proof Artifact(s)
- File: `backend/app/ollama/errors.py` — error hierarchy with 4 exception classes, sanitized messages (no raw response forwarding)
- File: `backend/app/ollama/models.py` — `EmbeddingResult` (vector, dimensions, model) and `EmbeddingSource` StrEnum
- File: `backend/app/ollama/client.py` — `OllamaEmbeddingClient` with `embed()` and `health()` methods
- File: `backend/app/ollama/__init__.py` — `__all__` re-exports mirroring `jellyfin/__init__.py` pattern
- File: `backend/app/config.py` — `ollama_embed_timeout: int = 120` and `ollama_health_timeout: int = 5` added to `Settings`
- Test: `backend/tests/test_ollama_client.py` — unit tests with mocked httpx covering: successful embed returns `EmbeddingResult` with correct dimensions; `OllamaConnectionError` on transport error; `OllamaTimeoutError` on timeout; `OllamaModelError` on 404; `OllamaError` on other non-2xx; `health()` returns True on 200 and False on error/timeout/non-200; error messages contain no raw Ollama response text; INFO log includes dimensions and elapsed time but NOT input text
- Test: `backend/tests/test_ollama_client.py` — unit tests for new config fields verifying defaults
- Test: `@pytest.mark.integration` — `embed()` against real Ollama returns 768-dim vector; `health()` returns True

#### 1.0 Tasks

- [x] 1.1Create `backend/app/ollama/errors.py` with four exception classes: `OllamaError` (base), `OllamaConnectionError(OllamaError)`, `OllamaTimeoutError(OllamaError)`, `OllamaModelError(OllamaError)`. Each class has a docstring. Mirror the `jellyfin/errors.py` pattern.
- [x] 1.2 Create `backend/app/ollama/models.py` with `EmbeddingSource` (StrEnum with values `"jellyfin_only"` and `"tmdb_enriched"`) and `EmbeddingResult` (Pydantic model with fields: `vector: list[float]`, `dimensions: int`, `model: str`).
- [x] 1.3 Add `ollama_embed_timeout: int = 120` and `ollama_health_timeout: int = 5` fields to `Settings` in `backend/app/config.py`, placed in the existing `# Ollama` section.
- [x] 1.4 Create `backend/app/ollama/client.py` with `OllamaEmbeddingClient` class. Constructor: `__init__(self, base_url: str, http_client: httpx.AsyncClient, embed_model: str = "nomic-embed-text")`. Store `_base_url` (stripped trailing slash), `_client`, `_embed_model`. Add docstring documenting the network trust assumption (Ollama is a trusted, network-local service).
- [x] 1.5 Implement `async def embed(self, text: str) -> EmbeddingResult` on `OllamaEmbeddingClient`: POST to `{base_url}/api/embed` with `{"model": self._embed_model, "input": text}`. Parse `response.json()["embeddings"][0]` into `EmbeddingResult`. Map `httpx.TimeoutException` to `OllamaTimeoutError`, `httpx.TransportError` (excluding `TimeoutException`) to `OllamaConnectionError`, HTTP 404 to `OllamaModelError`, other non-2xx to `OllamaError`. All error messages are sanitized strings (never forward `response.text`).
- [x] 1.6 Add logging to `embed()`: INFO log with dimensions and elapsed_ms (e.g., `"ollama_embed dims=768 elapsed_ms=142"`). DEBUG log with first 100 chars of input text. Use `time.perf_counter()` for timing.
- [x] 1.7 Implement `async def health(self) -> bool` on `OllamaEmbeddingClient`: GET `{base_url}/` with per-request timeout override via `httpx`'s `timeout` kwarg (use the `health_timeout` passed to constructor or a default). Return `True` on HTTP 200, `False` on any exception or non-200. Never raises.
- [x] 1.8 Update `OllamaEmbeddingClient.__init__` to accept `health_timeout: float = 5.0` parameter and store it as `_health_timeout` for use by `health()`.
- [x] 1.9 Create `backend/app/ollama/__init__.py` with `__all__` re-exporting: `OllamaEmbeddingClient`, `OllamaError`, `OllamaConnectionError`, `OllamaTimeoutError`, `OllamaModelError`, `EmbeddingResult`, `EmbeddingSource`. Mirror the `jellyfin/__init__.py` import style.
- [x] 1.10 Write unit tests in `backend/tests/test_ollama_client.py` — `TestErrorHierarchy` class: verify each error subclasses `OllamaError`, verify `OllamaError` subclasses `Exception`, verify error message strings.
- [x] 1.11 Write unit tests — `TestEmbeddingResult` class: verify construction with valid data, verify `dimensions` field, verify `model` field. `TestEmbeddingSource` class: verify enum values `"jellyfin_only"` and `"tmdb_enriched"`.
- [x] 1.12 Write unit tests — `TestEmbed` class with `mock_http` and `ollama_client` fixtures (mirroring `test_jellyfin_client.py` pattern). Tests: successful embed returns `EmbeddingResult` with correct vector/dimensions/model; `OllamaConnectionError` raised on `httpx.ConnectError`; `OllamaTimeoutError` raised on `httpx.ReadTimeout`; `OllamaModelError` raised on HTTP 404; `OllamaError` raised on HTTP 500; verify POST URL is `{base_url}/api/embed`; verify JSON body contains correct model and input.
- [x] 1.13 Write unit tests — `TestHealth` class: returns `True` on HTTP 200; returns `False` on `httpx.ConnectError`; returns `False` on `httpx.ReadTimeout`; returns `False` on HTTP 500; verify per-request timeout kwarg is passed (inspect `mock_http.get` call args).
- [x] 1.14 Write unit tests — `TestErrorSanitization` class: trigger each error path (connection, timeout, model, generic) and assert that `str(exc)` does NOT contain mock response body text. Ensures raw Ollama responses never leak into exception messages.
- [x] 1.15 Write unit tests — `TestEmbedLogging` class: use `caplog` fixture to verify INFO log contains `dims=` and `elapsed_ms=` but does NOT contain the input text. Verify DEBUG log contains truncated input text (first 100 chars).
- [x] 1.16 Write unit tests — `TestConfigOllamaFields` class: instantiate `Settings` with minimal required fields and verify `ollama_embed_timeout` defaults to `120` and `ollama_health_timeout` defaults to `5`.
- [x] 1.17 Write integration tests (marked `@pytest.mark.integration`) in `backend/tests/test_ollama_client.py`: `embed()` against real Ollama with `nomic-embed-text` returns `EmbeddingResult` with 768-dimensional vector; `health()` returns `True` when Ollama is running.

---

### [x] 2.0 Composite Text Builder + Template Versioning

Create `backend/app/ollama/text_builder.py` with `TEMPLATE_VERSION = 1` constant, `CompositeTextResult` Pydantic model, and `build_composite_text(item: LibraryItem) -> CompositeTextResult` function. The builder transforms Jellyfin `LibraryItem` metadata into deterministic, embeddable strings using a structured template (not raw f-string concatenation). Missing/empty fields are omitted entirely — no placeholders. Returns `EmbeddingSource.JELLYFIN_ONLY` for all current output. Logs WARNING at 6000+ characters. Re-export `CompositeTextResult` from `__init__.py`.

#### 2.0 Proof Artifact(s)
- File: `backend/app/ollama/text_builder.py` — `TEMPLATE_VERSION`, `CompositeTextResult`, `build_composite_text()` using structured section builders
- File: `backend/app/ollama/__init__.py` — updated with `CompositeTextResult` and `build_composite_text` re-exports
- Test: `backend/tests/test_text_builder.py` — unit tests covering: full item produces exact expected template output; minimal item (name/id/type only) produces `"Title: {name}."`; missing overview omits overview section; empty genres list omits "Genres:" section; missing production_year omits "Year:" section; `template_version` matches `TEMPLATE_VERSION` constant; `source` is `EmbeddingSource.JELLYFIN_ONLY`
- Test: `backend/tests/test_text_builder.py` — snapshot/golden tests locking exact output for 3-5 representative `LibraryItem` inputs (detects accidental whitespace, punctuation, or ordering drift)
- Test: `backend/tests/test_text_builder.py` — determinism test: same input called twice produces byte-identical output
- Test: `backend/tests/test_text_builder.py` — 6000-char warning test: long overview triggers WARNING log
- Test: `@pytest.mark.integration` — build composite text from representative item, embed via Ollama client, verify 768-dim vector returned

#### 2.0 Tasks

- [x] 2.1 Create `backend/app/ollama/text_builder.py` with module-level `TEMPLATE_VERSION: int = 1` constant.
- [x] 2.2 Define `CompositeTextResult` Pydantic model in `text_builder.py` with fields: `text: str`, `template_version: int`, `source: EmbeddingSource`.
- [x] 2.3 Implement `build_composite_text(item: LibraryItem) -> CompositeTextResult` using structured section builders (list of optional sections joined with space). Mandatory section: `"Title: {item.name}."`. Optional sections: overview (appended as-is after title if present), `"Genres: {comma-separated}."` (only if genres is non-empty), `"Year: {production_year}."` (only if production_year is not None). No raw f-string concatenation — build a list of section strings and join with `" "`.
- [x] 2.4 Add WARNING log in `build_composite_text()` when the resulting text exceeds 6000 characters. No truncation. Use `logging.getLogger(__name__)`. Log the item name and text length, not the text content.
- [x] 2.5 Add DEBUG log in `build_composite_text()` with the full composite text (for troubleshooting only, never at INFO).
- [x] 2.6 Update `backend/app/ollama/__init__.py` to add `CompositeTextResult`, `build_composite_text`, and `TEMPLATE_VERSION` to imports and `__all__`.
- [x] 2.7 Write unit tests in `backend/tests/test_text_builder.py` — `TestBuildCompositeText` class: full item (all fields) produces exact expected output string matching template `"Title: {name}. {overview} Genres: {genres}. Year: {year}."`. Verify `template_version == TEMPLATE_VERSION`. Verify `source == EmbeddingSource.JELLYFIN_ONLY`.
- [x] 2.8 Write unit tests — minimal item (only `id`, `name`, `type` set): output is exactly `"Title: {name}."` with no trailing empty sections or extra whitespace.
- [x] 2.9 Write unit tests — missing field combinations: item with no overview (overview section omitted); item with empty genres list (Genres section omitted); item with no production_year (Year section omitted); item with only overview and no genres/year; item with only genres and no overview/year.
- [x] 2.10 Write snapshot/golden tests — `TestCompositeTextSnapshots` class: define 3-5 representative `LibraryItem` inputs (e.g., full sci-fi movie, minimal item, item with long overview, item with many genres, item with only name+overview). Assert exact output string matches hardcoded expected values. These tests lock down template formatting and detect accidental whitespace, punctuation, or ordering drift.
- [x] 2.11 Write determinism test — call `build_composite_text()` twice with identical `LibraryItem` input, assert `result1.text == result2.text` (byte-identical).
- [x] 2.12 Write 6000-char warning test — create a `LibraryItem` with an extremely long overview (>6000 chars), use `caplog` to verify a WARNING is logged containing the item name and text length.
- [x] 2.13 Write integration test (marked `@pytest.mark.integration`) in `backend/tests/test_text_builder.py`: build composite text from a representative `LibraryItem`, embed it via `OllamaEmbeddingClient`, verify a 768-dimensional vector is returned.

---

### [ ] 3.0 End-to-End Wiring + Health Integration

Wire `OllamaEmbeddingClient` into the application lifespan in `main.py`: create a SEPARATE `httpx.AsyncClient` with `timeout=settings.ollama_embed_timeout`, instantiate `OllamaEmbeddingClient`, store on `app.state.ollama_client`. LIFO shutdown order (Ollama httpx closed before Jellyfin httpx). Update `/health` endpoint to use `OllamaEmbeddingClient.health()` instead of ad-hoc `_check_service()` for Ollama status. Update `.env.example` with new config fields. Document network trust assumption in `OllamaEmbeddingClient` docstring.

#### 3.0 Proof Artifact(s)
- File: `backend/app/main.py` — lifespan creates Ollama httpx client + `OllamaEmbeddingClient` on `app.state`, LIFO shutdown order
- File: `backend/app/main.py` — `/health` endpoint uses `OllamaEmbeddingClient.health()` for Ollama status
- File: `.env.example` — contains `OLLAMA_EMBED_TIMEOUT=120` and `OLLAMA_HEALTH_TIMEOUT=5` (commented out with defaults documented)
- Test: `backend/tests/test_main.py` or `backend/tests/test_lifespan.py` — unit test verifying `app.state.ollama_client` is set after startup and httpx client is closed on shutdown
- Test: `backend/tests/test_main.py` — unit test verifying `/health` endpoint uses `OllamaEmbeddingClient.health()` and returns correct status structure
- Test: `@pytest.mark.integration` — full pipeline: create `LibraryItem` -> `build_composite_text()` -> `embed()` -> verify 768-dim vector; verify cosine similarity is higher for similar movies (two sci-fi) than dissimilar (sci-fi vs romantic comedy)
- Verify: `.env.example` contains new fields — `grep OLLAMA_EMBED_TIMEOUT .env.example && grep OLLAMA_HEALTH_TIMEOUT .env.example`

#### 3.0 Tasks

- [ ] 3.1 Update `backend/app/main.py` lifespan: after creating the Jellyfin httpx client, create a separate Ollama httpx client: `ollama_http = httpx.AsyncClient(timeout=settings.ollama_embed_timeout)`. Import `OllamaEmbeddingClient` from `app.ollama`.
- [ ] 3.2 Instantiate `OllamaEmbeddingClient` in lifespan: `ollama_client = OllamaEmbeddingClient(base_url=settings.ollama_host, http_client=ollama_http, embed_model=settings.ollama_embed_model, health_timeout=settings.ollama_health_timeout)`. Store as `app.state.ollama_client`.
- [ ] 3.3 Update lifespan shutdown to close `ollama_http` BEFORE `http_client` (Jellyfin) — LIFO order. Add `await ollama_http.aclose()` before the existing `await http_client.aclose()` line.
- [ ] 3.4 Update the startup connectivity check: replace the ad-hoc `_check_service()` call for Ollama with `ollama_client.health()`. Convert the boolean result to `"ok"` / `"error"` for the existing log message format.
- [ ] 3.5 Update the `/health` endpoint: replace the ad-hoc `_check_service()` call for Ollama with `app.state.ollama_client.health()`. Convert the boolean to `ServiceStatus` (`"ok"` if True, `"error"` if False). Keep the Jellyfin `_check_service()` call unchanged.
- [ ] 3.6 Remove the Ollama-specific `_check_service()` usage from the `/health` endpoint. The `_check_service()` helper can remain for Jellyfin; only the Ollama path changes. Clean up the unused `asyncio.gather` if both calls are no longer grouped together, or restructure to gather both (Jellyfin via `_check_service`, Ollama via `health()`).
- [ ] 3.7 Update `.env.example`: add `OLLAMA_EMBED_TIMEOUT=120` and `OLLAMA_HEALTH_TIMEOUT=5` as commented-out entries in the `# --- Ollama ---` section, with comments documenting the defaults and purpose (e.g., `# Timeout in seconds for embedding requests (default: 120)`).
- [ ] 3.8 Write unit tests in `backend/tests/test_main.py` (or `test_lifespan.py`): verify that after lifespan startup, `app.state.ollama_client` is an instance of `OllamaEmbeddingClient`. Verify that on shutdown, the Ollama httpx client's `aclose()` is called.
- [ ] 3.9 Write unit tests: mock `OllamaEmbeddingClient.health()` to return `True` and verify `/health` endpoint returns `{"ollama": "ok", ...}`. Mock it to return `False` and verify `/health` returns `{"ollama": "error", ...}`.
- [ ] 3.10 Write unit tests: verify LIFO shutdown order — Ollama httpx `aclose()` is called before Jellyfin httpx `aclose()`. Use mock call order tracking.
- [ ] 3.11 Write integration test (marked `@pytest.mark.integration`): full pipeline test — create a `LibraryItem` with realistic data, call `build_composite_text()`, pass result to `OllamaEmbeddingClient.embed()`, verify returned vector has 768 dimensions.
- [ ] 3.12 Write integration test (marked `@pytest.mark.integration`): semantic similarity verification — create two similar `LibraryItem`s (e.g., both sci-fi: "Alien" and "Aliens") and one dissimilar (e.g., romantic comedy). Build composite text for each, embed all three, compute cosine similarity. Assert `similarity(sci-fi A, sci-fi B) > similarity(sci-fi A, romcom)`.
- [ ] 3.13 Verify `.env.example` contains new fields: run `grep OLLAMA_EMBED_TIMEOUT .env.example && grep OLLAMA_HEALTH_TIMEOUT .env.example` and confirm both are present.
