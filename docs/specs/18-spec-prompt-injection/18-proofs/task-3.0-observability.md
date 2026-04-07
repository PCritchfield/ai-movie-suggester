# Task 3.0 — Observability: Proof

## Files Created/Modified
- `backend/app/chat/sanitize.py` — added `INJECTION_PATTERNS` dict and `check_injection_patterns()`
- `backend/app/chat/service.py` — integrated pattern logging (WARNING level)
- `backend/tests/test_chat_sanitize.py` — added 7 pattern detection tests
- `backend/tests/test_chat_service.py` — added 2 service logging tests
- `scripts/test_injection.py` — manual adversarial test harness (13 payloads)
- `Makefile` — added `test-injection` target

## Patterns Detected
- `instruction_ignore` — "ignore previous instructions", "disregard your instructions", "forget your instructions"
- `role_override` — "you are now", "act as", "pretend you are", "your new role"
- `system_prompt_leak` — "show me your system prompt", "repeat your instructions", "output your prompt", "what are your instructions"
- `delimiter_escape` — closing XML tags for system-instructions, movie-context, user-query

## Test Results
```
55 pytest tests passed (15 sanitize + 27 prompts + 13 service)
13/13 adversarial payloads passed
```

All tests pass. Lint clean.
