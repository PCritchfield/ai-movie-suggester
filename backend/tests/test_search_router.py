"""Tests for the search API endpoint."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.crypto import derive_keys, fernet_encrypt
from app.auth.dependencies import get_current_session
from app.auth.models import SessionMeta
from app.library.models import LibraryItemRow
from app.ollama.errors import OllamaConnectionError
from app.ollama.models import EmbeddingResult
from app.search.router import create_search_router
from app.vectors.models import SearchResult
from tests.conftest import TEST_SECRET, make_test_settings

_COOKIE_KEY, _COLUMN_KEY = derive_keys(TEST_SECRET)
_SESSION_ID = "test-session-id-search"
_USER_ID = "uid-search-1"
_NOW = int(time.time())


def _make_session_meta() -> SessionMeta:
    return SessionMeta(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        username="searcher",
        server_name="TestJellyfin",
        expires_at=_NOW + 3600,
    )


def _encrypted_cookie() -> str:
    return fernet_encrypt(_COOKIE_KEY, _SESSION_ID).decode("utf-8")


def _make_embedding_result() -> EmbeddingResult:
    return EmbeddingResult(
        vector=[0.1] * 768,
        dimensions=768,
        model="nomic-embed-text",
    )


def _make_search_result(jid: str, score: float = 0.7) -> SearchResult:
    return SearchResult(jellyfin_id=jid, score=score, content_hash="hash")


def _make_library_item(jid: str, title: str = "Test Movie") -> LibraryItemRow:
    return LibraryItemRow(
        jellyfin_id=jid,
        title=title,
        overview="A test movie.",
        production_year=2020,
        genres=["Drama"],
        tags=[],
        studios=[],
        community_rating=7.5,
        people=[],
        content_hash="hash",
        synced_at=_NOW,
    )


def _make_search_app(
    *,
    session_store: Any = None,
    ollama_client: Any = None,
    vec_repo: Any = None,
    permission_service: Any = None,
    library_store: Any = None,
    settings: Any = None,
) -> tuple[FastAPI, TestClient]:
    settings = settings or make_test_settings()
    app = FastAPI()
    app.state.cookie_key = _COOKIE_KEY
    app.state.session_store = session_store or AsyncMock()
    app.state.ollama_client = ollama_client or AsyncMock()
    app.state.vec_repo = vec_repo or AsyncMock()
    app.state.permission_service = permission_service or AsyncMock()
    app.state.library_store = library_store or AsyncMock()
    app.state.settings = settings
    app.state.limiter = None  # disable rate limiting in tests

    search_router = create_search_router(settings=settings, limiter=None)
    app.include_router(search_router)

    # Override auth dependency for testing
    async def _mock_session() -> SessionMeta:
        return _make_session_meta()

    app.dependency_overrides[get_current_session] = _mock_session

    return app, TestClient(app)


class TestSearchReturnsResults:
    def test_valid_query_returns_results(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.search.return_value = [
            _make_search_result("movie-1", 0.8),
            _make_search_result("movie-2", 0.6),
        ]
        vec_repo.count.return_value = 10

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["movie-1", "movie-2"]

        library = AsyncMock()
        library.get_many.return_value = [
            _make_library_item("movie-1", "Galaxy Quest"),
            _make_library_item("movie-2", "Spaceballs"),
        ]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token-abc"

        _, client = _make_search_app(
            session_store=session_store,
            ollama_client=ollama,
            vec_repo=vec_repo,
            permission_service=permissions,
            library_store=library,
        )

        resp = client.post(
            "/api/search",
            json={"query": "funny space movie", "limit": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["results"]) == 2
        assert data["results"][0]["title"] == "Galaxy Quest"
        assert data["results"][0]["score"] == 0.8
        assert data["results"][0]["poster_url"] == "/Items/movie-1/Images/Primary"
        assert "total_candidates" in data
        assert "filtered_count" in data
        assert "query_time_ms" in data


class TestSearchPermissionFiltering:
    def test_results_only_contain_permitted_items(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.search.return_value = [
            _make_search_result("allowed-1", 0.9),
            _make_search_result("forbidden-1", 0.8),
            _make_search_result("allowed-2", 0.7),
            _make_search_result("forbidden-2", 0.6),
            _make_search_result("allowed-3", 0.5),
        ]
        vec_repo.count.return_value = 10

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = [
            "allowed-1",
            "allowed-2",
            "allowed-3",
        ]

        library = AsyncMock()
        library.get_many.return_value = [
            _make_library_item("allowed-1"),
            _make_library_item("allowed-2"),
            _make_library_item("allowed-3"),
        ]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token"

        _, client = _make_search_app(
            session_store=session_store,
            ollama_client=ollama,
            vec_repo=vec_repo,
            permission_service=permissions,
            library_store=library,
        )

        resp = client.post("/api/search", json={"query": "test"})
        assert resp.status_code == 200
        data = resp.json()
        result_ids = [r["jellyfin_id"] for r in data["results"]]
        assert "forbidden-1" not in result_ids
        assert "forbidden-2" not in result_ids
        assert len(result_ids) == 3
        assert data["filtered_count"] == 2


class TestSearchRequiresAuth:
    def test_unauthenticated_returns_401(self) -> None:
        app = FastAPI()
        settings = make_test_settings()
        search_router = create_search_router(settings=settings, limiter=None)
        app.include_router(search_router)
        app.state.cookie_key = _COOKIE_KEY
        app.state.session_store = AsyncMock()
        app.state.settings = settings
        # Do NOT override get_current_session — let it fail naturally
        client = TestClient(app)
        resp = client.post("/api/search", json={"query": "test"})
        assert resp.status_code == 401


class TestSearchInvalidQuery:
    def test_empty_query_returns_422(self) -> None:
        _, client = _make_search_app()
        resp = client.post("/api/search", json={"query": "", "limit": 10})
        assert resp.status_code == 422

    def test_too_long_query_returns_422(self) -> None:
        _, client = _make_search_app()
        resp = client.post("/api/search", json={"query": "x" * 1001})
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self) -> None:
        _, client = _make_search_app()
        resp = client.post("/api/search", json={"query": "test", "limit": 0})
        assert resp.status_code == 422

    def test_limit_too_high_returns_422(self) -> None:
        _, client = _make_search_app()
        resp = client.post("/api/search", json={"query": "test", "limit": 51})
        assert resp.status_code == 422


class TestSearchResponseMetadata:
    def test_response_includes_metadata(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.search.return_value = [
            _make_search_result("m1", 0.9),
            _make_search_result("m2", 0.8),
        ]
        vec_repo.count.return_value = 10

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]  # m2 filtered

        library = AsyncMock()
        library.get_many.return_value = [_make_library_item("m1")]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token"

        _, client = _make_search_app(
            session_store=session_store,
            ollama_client=ollama,
            vec_repo=vec_repo,
            permission_service=permissions,
            library_store=library,
        )

        resp = client.post("/api/search", json={"query": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_candidates"] == 2
        assert data["filtered_count"] == 1
        assert isinstance(data["query_time_ms"], int)
        assert data["query_time_ms"] >= 0


class TestSearchOllamaDown:
    def test_ollama_connection_error_returns_503(self) -> None:
        ollama = AsyncMock()
        ollama.embed.side_effect = OllamaConnectionError("Cannot reach Ollama")

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10

        library = AsyncMock()
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token"

        _, client = _make_search_app(
            session_store=session_store,
            ollama_client=ollama,
            vec_repo=vec_repo,
            library_store=library,
        )

        resp = client.post("/api/search", json={"query": "test"})
        assert resp.status_code == 503
        assert "embedding service" in resp.json()["detail"].lower()
