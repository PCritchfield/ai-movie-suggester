# Task 3.0 Proof Artifacts — ChatService + Router with SSE Streaming

## Test Output

```
$ cd backend && uv run pytest tests/test_chat_service.py tests/test_chat_router.py -x -q
............                                                             [100%]
12 passed in 0.07s
```

## Tests Implemented

| Test | Status | Assertion |
|------|--------|-----------|
| `test_chat_service_yields_metadata_first` | PASS | Metadata event first, text events, done event |
| `test_chat_service_empty_results` | PASS | Empty results -> empty recommendations, LLM still responds |
| `test_chat_service_connection_error` | PASS | OllamaConnectionError -> error event with code "ollama_unavailable" |
| `test_chat_service_unexpected_error` | PASS | RuntimeError -> error event with code "stream_interrupted" |
| `test_unauthenticated_returns_401` | PASS | No auth -> 401 |
| `test_empty_message_returns_422` | PASS | Empty message -> 422 |
| `test_too_long_message_returns_422` | PASS | Message > 1000 chars -> 422 |
| `test_ollama_down_returns_503` | PASS | Ollama health false -> 503 |
| `test_chat_endpoint_streams_sse` | PASS | Full SSE stream: metadata, text, done |
| `test_chat_endpoint_metadata_first` | PASS | First event is metadata with recommendations |
| `test_chat_endpoint_no_results` | PASS | Empty recommendations, LLM still responds |
| `test_chat_endpoint_mid_stream_error` | PASS | Mid-stream error yields SSE error event |

## Lint Output

```
$ cd backend && uv run ruff check app/chat/ tests/test_chat_service.py tests/test_chat_router.py
All checks passed!
```

## Full Suite Regression Check

```
$ cd backend && uv run pytest tests/ -x -q --ignore=tests/integration -m "not ollama_integration"
551 passed, 5 deselected in 4.61s
```

## Files Changed

- `backend/app/chat/models.py` — ChatRequest Pydantic model
- `backend/app/chat/service.py` — ChatService with search -> prompt -> stream pipeline
- `backend/app/chat/router.py` — create_chat_router() factory with SSE streaming
- `backend/tests/test_chat_service.py` — 4 service tests
- `backend/tests/test_chat_router.py` — 8 router tests
