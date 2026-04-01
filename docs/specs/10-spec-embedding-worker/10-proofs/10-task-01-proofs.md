# Task 1.0 Proofs — Store Methods, Schema Migration, and Settings

## Test Results

```
tests/test_library_store_embedding.py::TestBusyTimeout::test_busy_timeout_set PASSED
tests/test_library_store_embedding.py::TestLastAttemptedAtMigration::test_column_exists_after_init PASSED
tests/test_library_store_embedding.py::TestLastAttemptedAtMigration::test_migration_idempotent PASSED
tests/test_library_store_embedding.py::TestEnqueueOnConflictResetsLastAttemptedAt::test_reenqueue_resets_last_attempted_at PASSED
tests/test_library_store_embedding.py::TestGetRetryableItems::test_returns_pending_items PASSED
tests/test_library_store_embedding.py::TestGetRetryableItems::test_skips_items_within_cooldown PASSED
tests/test_library_store_embedding.py::TestGetRetryableItems::test_skips_items_exceeding_max_retries PASSED
tests/test_library_store_embedding.py::TestGetRetryableItems::test_respects_batch_size PASSED
tests/test_library_store_embedding.py::TestClaimBatch::test_transitions_pending_to_processing PASSED
tests/test_library_store_embedding.py::TestClaimBatch::test_returns_zero_for_non_pending PASSED
tests/test_library_store_embedding.py::TestClaimBatch::test_empty_ids_returns_zero PASSED
tests/test_library_store_embedding.py::TestMarkEmbedded::test_deletes_queue_row PASSED
tests/test_library_store_embedding.py::TestMarkEmbeddedMany::test_deletes_multiple_rows PASSED
tests/test_library_store_embedding.py::TestMarkEmbeddedMany::test_empty_list_returns_zero PASSED
tests/test_library_store_embedding.py::TestMarkAttempt::test_increments_retry_and_sets_error PASSED
tests/test_library_store_embedding.py::TestMarkAttempt::test_multiple_attempts_increment PASSED
tests/test_library_store_embedding.py::TestMarkFailedPermanent::test_sets_status_to_failed PASSED
tests/test_library_store_embedding.py::TestResetStaleProcessing::test_resets_processing_to_pending PASSED
tests/test_library_store_embedding.py::TestResetStaleProcessing::test_does_not_affect_pending_items PASSED
tests/test_library_store_embedding.py::TestResetStaleProcessing::test_does_not_affect_failed_items PASSED
tests/test_library_store_embedding.py::TestGetFailedItems::test_returns_failed_item_details PASSED
tests/test_library_store_embedding.py::TestGetFailedItems::test_empty_when_no_failures PASSED
tests/test_library_store_embedding.py::TestGetQueueCounts::test_correct_breakdown PASSED
tests/test_library_store_embedding.py::TestGetQueueCounts::test_empty_queue PASSED

tests/test_config.py::test_embedding_batch_size_default PASSED
tests/test_config.py::test_embedding_worker_interval_seconds_default PASSED
tests/test_config.py::test_embedding_max_retries_default PASSED
tests/test_config.py::test_embedding_cooldown_seconds_default PASSED
tests/test_config.py::test_embedding_batch_size_env_override PASSED
tests/test_config.py::test_embedding_batch_size_rejects_zero PASSED
tests/test_config.py::test_embedding_batch_size_rejects_over_50 PASSED

66 passed in 0.17s
```

## CLI Verification — busy_timeout Pragma

The `test_busy_timeout_set` test verifies `PRAGMA busy_timeout` returns 5000 on a freshly initialized LibraryStore connection.

## Lint Output

```
All checks passed!
```

## Configuration Examples

New environment variables added to `.env.example`:

```
# Embedding Worker
# EMBEDDING_BATCH_SIZE=10                  # Items per processing cycle (1-50)
# EMBEDDING_WORKER_INTERVAL_SECONDS=300    # Poll interval in seconds
# EMBEDDING_MAX_RETRIES=3                  # Max transient retries before marking failed
# EMBEDDING_COOLDOWN_SECONDS=300           # Min seconds between retry attempts
```

## Verification Summary

- 24 new tests for queue management methods — all pass
- 7 new tests for Settings fields — all pass
- busy_timeout pragma verified via test
- ON CONFLICT clause resets `last_attempted_at` to NULL — verified via test
- All lint checks pass
