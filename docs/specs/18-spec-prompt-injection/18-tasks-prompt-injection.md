# Spec 18 — Prompt Injection Mitigation: Task List

## Task 1.0: Input Sanitization
- [x] 1.1 Create `backend/app/chat/sanitize.py` with `sanitize_user_input()`
- [x] 1.2 Integrate sanitization in `ChatService.stream()`
- [x] 1.3 Write 8 tests in `backend/tests/test_chat_sanitize.py`

## Task 2.0: Prompt Delineation
- [ ] 2.1 Update STRUCTURAL_FRAMING anti-injection clause
- [ ] 2.2 Update CONTEXT_PREFIX to XML `<movie-context>` tag
- [ ] 2.3 Add CONTEXT_SUFFIX closing tag
- [ ] 2.4 Wrap `get_system_prompt()` output in `<system-instructions>` tags
- [ ] 2.5 Update `build_chat_messages()` for context suffix and query wrapping
- [ ] 2.6 Update ALL existing tests in `test_chat_prompts.py`
- [ ] 2.7 Write 8 new XML structure tests

## Task 3.0: Observability
- [ ] 3.1 Add `INJECTION_PATTERNS` and `check_injection_patterns()` to `sanitize.py`
- [ ] 3.2 Integrate pattern logging in `ChatService.stream()`
- [ ] 3.3 Write 7 pattern detection tests + 2 service logging tests
- [ ] 3.4 Create `scripts/test_injection.py` manual harness
- [ ] 3.5 Add `test-injection` Makefile target
