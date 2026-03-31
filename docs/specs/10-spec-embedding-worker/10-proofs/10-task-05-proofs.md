# Task 5.0 Proofs — Observability Endpoints and Lifespan Wiring

## Test Results

```
489 passed, 18 deselected, 35 warnings in 4.11s
```

### Health Embedding Tests (5 tests)
```
tests/test_health_embeddings.py::TestHealthEmbeddings::test_health_includes_embeddings_section PASSED
tests/test_health_embeddings.py::TestHealthEmbeddings::test_health_embeddings_has_pending_field PASSED
tests/test_health_embeddings.py::TestHealthEmbeddings::test_health_embeddings_has_failed_field PASSED
tests/test_health_embeddings.py::TestHealthEmbeddings::test_health_embeddings_has_worker_status PASSED
tests/test_health_embeddings.py::TestHealthEmbeddings::test_health_embeddings_has_total_field PASSED
```

### Admin Embedding Endpoint Tests (6 tests)
```
tests/test_embedding_admin.py::TestEmbeddingAdminAuth::test_no_session_returns_401 PASSED
tests/test_embedding_admin.py::TestEmbeddingAdminAuth::test_non_admin_returns_403 PASSED
tests/test_embedding_admin.py::TestEmbeddingAdminAuth::test_admin_returns_200 PASSED
tests/test_embedding_admin.py::TestEmbeddingAdminResponse::test_response_includes_queue_counts PASSED
tests/test_embedding_admin.py::TestEmbeddingAdminResponse::test_response_includes_worker_state PASSED
tests/test_embedding_admin.py::TestEmbeddingAdminResponse::test_response_includes_batch_size_from_settings PASSED
```

### Lifespan Wiring Tests (3 tests)
```
tests/test_embedding_admin.py::TestLifespanWiring::test_embedding_worker_exists_on_app_state PASSED
tests/test_embedding_admin.py::TestLifespanWiring::test_embedding_worker_initial_status PASSED
tests/test_embedding_admin.py::TestLifespanWiring::test_app_state_has_settings PASSED
```

## Lint Output

```
All checks passed!
```

## Verification Summary

- `/health` returns real `pending`, `failed`, `total`, and `worker_status` from embedding queue
- `GET /api/admin/embedding/status` returns full queue breakdown, worker state, failed items list
- Admin endpoint requires authentication (401) and admin role (403)
- EmbeddingWorker created and started during lifespan with correct shutdown ordering
- SyncEngine sets embedding_event after run_sync() completes, waking the worker
- Embedding task cancelled BEFORE sync task in LIFO shutdown order
- 14 new tests for observability and wiring
