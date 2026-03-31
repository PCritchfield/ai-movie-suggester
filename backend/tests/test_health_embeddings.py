"""Tests for /health endpoint embedding status fields."""

from __future__ import annotations

from tests.conftest import make_test_client


class TestHealthEmbeddingFields:
    """Verify /health includes real embedding queue counts and worker status."""

    def test_health_includes_embedding_pending(self) -> None:
        """Health response contains embeddings.pending field."""
        client = make_test_client()
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "embeddings" in data
            assert "pending" in data["embeddings"]
            assert isinstance(data["embeddings"]["pending"], int)
        finally:
            client.close()

    def test_health_includes_embedding_failed(self) -> None:
        """Health response contains embeddings.failed field."""
        client = make_test_client()
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "failed" in data["embeddings"]
            assert isinstance(data["embeddings"]["failed"], int)
        finally:
            client.close()

    def test_health_includes_embedding_total(self) -> None:
        """Health response contains embeddings.total field."""
        client = make_test_client()
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "total" in data["embeddings"]
            assert isinstance(data["embeddings"]["total"], int)
        finally:
            client.close()

    def test_health_includes_worker_status(self) -> None:
        """Health response contains embeddings.worker_status field."""
        client = make_test_client()
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "worker_status" in data["embeddings"]
            assert data["embeddings"]["worker_status"] in ("idle", "processing")
        finally:
            client.close()

    def test_health_embedding_defaults_on_fresh_app(self) -> None:
        """Fresh app reports zero pending/failed and idle worker."""
        client = make_test_client()
        try:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            emb = data["embeddings"]
            assert emb["pending"] == 0
            assert emb["failed"] == 0
            assert emb["total"] == 0
            assert emb["worker_status"] == "idle"
        finally:
            client.close()
