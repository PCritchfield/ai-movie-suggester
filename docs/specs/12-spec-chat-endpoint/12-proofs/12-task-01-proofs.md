# Task 1.0 Proof Artifacts — OllamaChatClient + Config Changes

## Test Output

```
$ cd backend && uv run pytest tests/test_chat_client.py -x -q
................                                                         [100%]
16 passed in 0.04s
```

## Tests Implemented

| Test | Status | Assertion |
|------|--------|-----------|
| `test_stream_error_is_ollama_error` | PASS | `issubclass(OllamaStreamError, OllamaError)` |
| `test_stream_error_message` | PASS | Error message preserved |
| `test_chat_client_health_true` | PASS | `health()` returns True on 200 |
| `test_chat_client_health_false` | PASS | `health()` returns False on ConnectError |
| `test_chat_client_health_false_on_500` | PASS | `health()` returns False on 500 |
| `test_health_passes_timeout_kwarg` | PASS | timeout=5.0 passed |
| `test_health_uses_correct_url` | PASS | URL is `{base_url}/` |
| `test_chat_client_streams_tokens` | PASS | Yields "Hello", " world", skips empty done |
| `test_chat_client_does_not_yield_empty_on_done` | PASS | Empty content not yielded |
| `test_chat_client_connection_error` | PASS | OllamaConnectionError raised |
| `test_chat_client_timeout` | PASS | OllamaTimeoutError raised |
| `test_chat_client_malformed_json` | PASS | OllamaStreamError raised |
| `test_chat_client_unexpected_shape` | PASS | OllamaStreamError raised |
| `test_base_url_trailing_slash_stripped` | PASS | Trailing slash removed |
| `test_default_batch_size` | PASS | `embedding_batch_size == 5` |
| `test_chat_system_prompt_default_none` | PASS | `chat_system_prompt is None` |

## Lint Output

```
$ cd backend && uv run ruff check app/ tests/
All checks passed!
```

## Full Suite Regression Check

```
$ cd backend && uv run pytest tests/ -x -q --ignore=tests/integration -m "not ollama_integration"
527 passed, 5 deselected in 4.67s
```

## Files Changed

- `backend/app/ollama/errors.py` — Added `OllamaStreamError`
- `backend/app/ollama/chat_client.py` — New `OllamaChatClient` with `health()` and `chat_stream()`
- `backend/app/config.py` — Added `chat_system_prompt`, changed `embedding_batch_size` default 10→5
- `backend/tests/test_config.py` — Updated batch size assertion to 5
- `backend/tests/test_chat_client.py` — 16 new tests
