# Task 5.0 Proof Artifacts — End-to-End Integration + Generation Timeout

## Test Output

```
$ cd backend && uv run pytest tests/ -x -q --ignore=tests/integration -m "not ollama_integration"
559 passed, 5 deselected in 4.85s
```

## Tests Implemented (new in this task)

| Test | Status | Assertion |
|------|--------|-----------|
| `test_chat_endpoint_generation_timeout` | PASS | SSE error event with code "generation_timeout" |
| `test_chat_endpoint_partial_embeddings` | PASS | Metadata search_status is "partial_embeddings", text follows |
| `test_chat_endpoint_stream_event_format` | PASS | All events have "type", metadata has "version: 1", text has "content", done has only "type" |

## Full Test Count

| Test File | Tests |
|-----------|-------|
| `test_chat_client.py` | 16 |
| `test_chat_prompts.py` | 12 |
| `test_chat_service.py` | 6 |
| `test_chat_router.py` | 11 |
| `test_embedding_worker.py` (pause tests) | 3 new |
| **Total new tests** | **48** |

## Lint Output

```
$ cd backend && uv run ruff check app/ tests/
All checks passed!
```

## Wiring Verification

main.py now:
- Creates `chat_ollama_http` with custom timeouts (connect=5s, read=300s, write=10s, pool=5s)
- Creates `OllamaChatClient` with `ollama_chat_model` from settings
- Creates `embedding_pause_event` (shared between EmbeddingWorker and ChatService)
- Passes `pause_event` to `EmbeddingWorker(...)`
- Creates `ChatService` with search_service, chat_client, pause_event, settings
- Creates and mounts chat router via `create_chat_router()`
- Closes `chat_ollama_http` in shutdown (LIFO, before embedding ollama_http)

## Files Changed

- `backend/app/main.py` — Wired chat client, service, pause event, router; shutdown cleanup
- `backend/tests/test_chat_router.py` — 3 new tests (timeout, partial, format)
- `docs/specs/12-spec-chat-endpoint/12-tasks-chat-endpoint.md` — All tasks marked [x]
