# 07 Task 3.0 Proof Artifacts — End-to-End Wiring + Health Integration

## Files Created

| File | Purpose |
|------|---------|
| `backend/tests/test_lifespan.py` | Lifespan wiring, LIFO shutdown, and full pipeline integration tests |

## Files Modified

| File | Change |
|------|--------|
| `backend/app/main.py` | Ollama httpx client + OllamaEmbeddingClient in lifespan; /health uses .health(); LIFO shutdown |
| `.env.example` | Added OLLAMA_EMBED_TIMEOUT and OLLAMA_HEALTH_TIMEOUT entries |
| `backend/tests/test_health.py` | Updated to mock OllamaEmbeddingClient.health() instead of old ad-hoc pattern |
| `backend/tests/conftest.py` | Updated make_test_client to enter lifespan context (needed for app.state access) |

## Test Results

```
206 passed, 15 deselected (integration), 17 warnings in 1.34s
```

## Test Coverage

### test_health.py (updated)
- `test_health_endpoint_returns_200` — basic health check
- `test_health_response_shape` — response includes jellyfin, ollama, embeddings
- `test_health_jellyfin_reports_status` — ok or error (not crash)
- `test_health_reports_ok_when_services_reachable` — mocked Jellyfin 200 + Ollama health True
- `test_health_ollama_error_when_health_returns_false` — Ollama health False -> "error"
- `test_health_ollama_ok_when_health_returns_true` — Ollama health True -> "ok"
- `test_health_embeddings_zero_until_epic2` — embeddings 0/0

### test_lifespan.py (new)
- `TestLifespanOllamaWiring.test_ollama_client_set_on_app_state` — app.state.ollama_client is OllamaEmbeddingClient
- `TestLifespanShutdownOrder.test_lifo_shutdown_order` — Ollama httpx closed before Jellyfin
- Integration: `test_full_pipeline_returns_768_dims` — LibraryItem -> text -> embed -> 768-dim
- Integration: `test_semantic_similarity_scifi_vs_romcom` — similar > dissimilar cosine similarity

## .env.example Verification

```
# OLLAMA_EMBED_TIMEOUT=120
# OLLAMA_HEALTH_TIMEOUT=5
```

## Lint/Format

- `ruff check` — 0 errors
- `ruff format --check` — all files formatted
