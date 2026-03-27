# 07 Task 1.0 Proof Artifacts — Ollama Embedding Client + Error Hierarchy

## Files Created

| File | Purpose |
|------|---------|
| `backend/app/ollama/errors.py` | Error hierarchy: `OllamaError` > `OllamaConnectionError`, `OllamaTimeoutError`, `OllamaModelError` |
| `backend/app/ollama/models.py` | `EmbeddingResult` Pydantic model, `EmbeddingSource` StrEnum |
| `backend/app/ollama/client.py` | `OllamaEmbeddingClient` with `embed()` and `health()` methods |
| `backend/app/ollama/__init__.py` | `__all__` re-exports mirroring `jellyfin/__init__.py` |
| `backend/tests/test_ollama_client.py` | 35 unit tests covering all client behavior |

## Files Modified

| File | Change |
|------|--------|
| `backend/app/config.py` | Added `ollama_embed_timeout: int = 120` and `ollama_health_timeout: int = 5` |

## Test Results

```
35 passed, 2 deselected (integration tests) in 0.05s
179 passed total (full suite), 12 deselected, 17 warnings in 0.84s
```

## Test Coverage

- `TestErrorHierarchy` — 7 tests: subclass relationships, error messages
- `TestEmbeddingResult` — 3 tests: construction, dimensions, model field
- `TestEmbeddingSource` — 2 tests: enum values for jellyfin_only and tmdb_enriched
- `TestEmbed` — 8 tests: success, connection error, timeout, model not found, server error, URL, JSON body, trailing slash, invalid response shape
- `TestHealth` — 6 tests: 200 returns True, connect error returns False, timeout returns False, 500 returns False, timeout kwarg passed, correct URL
- `TestErrorSanitization` — 4 tests: connection, timeout, model, generic errors all have sanitized messages
- `TestEmbedLogging` — 2 tests: INFO log has dims/elapsed_ms (no input text), DEBUG log has input preview
- `TestConfigOllamaFields` — 2 tests: defaults for embed_timeout and health_timeout
- `TestOllamaIntegration` — 2 integration tests (marked, skipped by default): embed returns 768-dim, health returns True

## Lint/Format

- `ruff check` — 0 errors
- `ruff format --check` — all files formatted
