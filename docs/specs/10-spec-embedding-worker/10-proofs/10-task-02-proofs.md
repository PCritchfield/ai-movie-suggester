# Task 2.0 Proofs — Ollama Batch Embedding API + Vector Batch Upsert

## Test Results

```
tests/test_ollama_embed_batch.py::TestEmbedBatchSuccess::test_batch_returns_correct_count PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchSuccess::test_batch_dimensions_correct PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchSuccess::test_batch_positional_mapping PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchSuccess::test_batch_sends_correct_json_body PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchSuccess::test_batch_posts_correct_url PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchEdgeCases::test_empty_input_returns_empty_list PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchEdgeCases::test_fewer_vectors_than_texts_raises PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchEdgeCases::test_dimension_mismatch_in_batch_raises PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchErrors::test_timeout_raises_ollama_timeout_error PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchErrors::test_connection_error_raises_ollama_connection_error PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchErrors::test_404_raises_ollama_model_error PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchErrors::test_500_raises_ollama_error PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchErrors::test_invalid_response_shape_raises_ollama_error PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchSanitization::test_connection_error_sanitized PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchSanitization::test_timeout_error_sanitized PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchSanitization::test_model_error_sanitized PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchSanitization::test_generic_error_sanitized PASSED
tests/test_ollama_embed_batch.py::TestEmbedBatchLogging::test_info_log_contains_count_and_elapsed PASSED

tests/test_vec_repo_upsert_many.py::TestUpsertManyBasic::test_batch_upsert_stores_all_items PASSED
tests/test_vec_repo_upsert_many.py::TestUpsertManyBasic::test_batch_upsert_records_retrievable PASSED
tests/test_vec_repo_upsert_many.py::TestUpsertManyBasic::test_duplicate_ids_in_batch_last_wins PASSED
tests/test_vec_repo_upsert_many.py::TestUpsertManyBasic::test_upsert_many_overwrites_existing PASSED
tests/test_vec_repo_upsert_many.py::TestUpsertManyEdgeCases::test_empty_input_is_noop PASSED
tests/test_vec_repo_upsert_many.py::TestUpsertManyEdgeCases::test_content_hash_set_correctly PASSED
tests/test_vec_repo_upsert_many.py::TestUpsertManyEdgeCases::test_embedded_at_set_correctly PASSED
tests/test_vec_repo_upsert_many.py::TestUpsertManyEdgeCases::test_embedding_status_is_complete PASSED
tests/test_vec_repo_upsert_many.py::TestUpsertManyRollback::test_mid_batch_failure_rolls_back_entire_transaction PASSED

27 passed in 0.15s
```

## Lint Output

```
All checks passed!
```

## Verification Summary

- 18 new tests for `embed_batch()` — all pass
  - Correct count, dimensions, positional mapping
  - Empty input returns empty (no HTTP call)
  - Fewer vectors than inputs raises `OllamaError`
  - Error wrapping: timeout, connection, 404, 500
  - Error sanitization: raw Ollama bodies never leak
  - Logging: count and elapsed_ms at INFO level
- 9 new tests for `upsert_many()` — all pass
  - Batch of 5 items all stored
  - Duplicate IDs: last write wins
  - Overwrites existing vectors
  - Empty input is no-op
  - Mid-batch failure rolls back entire transaction
  - content_hash, embedded_at, embedding_status set correctly
- VectorRepositoryProtocol updated with `upsert_many` signature
