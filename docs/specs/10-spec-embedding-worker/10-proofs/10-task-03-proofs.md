# Task 3.0 Proofs — Embedding Worker Core with Retry Policy

## Test Results

```
tests/test_embedding_worker.py::TestBuildText::test_full_metadata PASSED
tests/test_embedding_worker.py::TestBuildText::test_missing_overview PASSED
tests/test_embedding_worker.py::TestBuildText::test_empty_overview PASSED
tests/test_embedding_worker.py::TestBuildText::test_missing_genres PASSED
tests/test_embedding_worker.py::TestBuildText::test_missing_year PASSED
tests/test_embedding_worker.py::TestBuildText::test_title_only PASSED
tests/test_embedding_worker.py::TestProcessCycleHappyPath::test_batch_embed_and_upsert PASSED
tests/test_embedding_worker.py::TestProcessCycleEarlyExit::test_ollama_unhealthy_skips_cycle PASSED
tests/test_embedding_worker.py::TestProcessCycleEarlyExit::test_empty_queue_returns_early PASSED
tests/test_embedding_worker.py::TestProcessCycleEarlyExit::test_zero_claimed_returns_early PASSED
tests/test_embedding_worker.py::TestBatchFallback::test_batch_failure_falls_back_to_individual PASSED
tests/test_embedding_worker.py::TestErrorClassification::test_transient_error_marks_attempt PASSED
tests/test_embedding_worker.py::TestErrorClassification::test_permanent_error_model_not_found PASSED
tests/test_embedding_worker.py::TestErrorClassification::test_max_retries_exceeded_marks_permanent PASSED
tests/test_embedding_worker.py::TestErrorClassification::test_unexpected_exception_sanitized PASSED
tests/test_embedding_worker.py::TestErrorClassification::test_connection_error_transient PASSED
tests/test_embedding_worker.py::TestLockBehavior::test_lock_prevents_concurrent_processing PASSED
tests/test_embedding_worker.py::TestStartup::test_startup_resets_stale_processing PASSED
tests/test_embedding_worker.py::TestStatusTracking::test_initial_status_is_idle PASSED
tests/test_embedding_worker.py::TestStatusTracking::test_status_updates_during_cycle PASSED
tests/test_embedding_worker.py::TestRunLoop::test_run_cancellation PASSED
tests/test_embedding_worker.py::TestRunLoop::test_run_processes_on_event PASSED
tests/test_embedding_worker.py::TestRunLoop::test_run_catches_cycle_exception PASSED
tests/test_embedding_worker.py::TestMissingItem::test_missing_row_is_skipped PASSED

24 passed in 0.25s
```

## Lint Output

```
All checks passed!
```

## Verification Summary

- 24 unit tests covering all worker behaviors — all pass
- Happy path: claim → embed_batch → upsert_many → mark_embedded_many lifecycle
- Early exits: Ollama unhealthy, empty queue, zero claimed
- Batch fallback to individual processing on batch failure
- Error classification: transient (mark_attempt), permanent (OllamaModelError → mark_failed_permanent)
- Max retries exceeded → mark_failed_permanent
- Error message sanitization: raw exception strings never stored
- Lock prevents concurrent processing cycles
- Startup calls reset_stale_processing()
- Run loop: clean cancellation, event-driven processing, exception resilience
- Missing items gracefully skipped
