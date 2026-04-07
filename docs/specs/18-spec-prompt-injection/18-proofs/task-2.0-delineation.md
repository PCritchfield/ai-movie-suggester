# Task 2.0 — Prompt Delineation: Proof

## Files Modified
- `backend/app/chat/prompts.py` — updated STRUCTURAL_FRAMING, CONTEXT_PREFIX, added CONTEXT_SUFFIX, wrapped system prompt and query in XML tags
- `backend/tests/test_chat_prompts.py` — updated all existing tests + 8 new XML structure tests

## Changes Summary
1. STRUCTURAL_FRAMING now references `<movie-context>` tags and explicitly forbids following directives in metadata
2. CONTEXT_PREFIX changed from `"Available movies:\n"` to XML `<movie-context>` tag with data-only instruction
3. Added CONTEXT_SUFFIX = `"\n</movie-context>"`
4. `get_system_prompt()` wraps output in `<system-instructions>` tags
5. `build_chat_messages()` wraps context in full `<movie-context>` tags and query in `<user-query>` tags
6. Budget estimation includes CONTEXT_SUFFIX length

## Test Results
```
46 passed in 0.07s
```

All 46 tests pass (8 new XML tests + 19 updated existing tests + 8 sanitize + 11 service). Lint clean.
