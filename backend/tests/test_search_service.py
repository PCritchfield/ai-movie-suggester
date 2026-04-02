"""Unit tests for SearchService."""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.library.models import LibraryItemRow
from app.ollama.models import EmbeddingResult
from app.search.service import SearchService
from app.vectors.models import SearchResult

_NOW = 1700000000


def _make_embedding_result() -> EmbeddingResult:
    return EmbeddingResult(vector=[0.1] * 768, dimensions=768, model="nomic-embed-text")


def _make_search_result(jid: str, score: float = 0.7) -> SearchResult:
    return SearchResult(jellyfin_id=jid, score=score, content_hash="hash")


def _make_library_item(jid: str, title: str = "Movie") -> LibraryItemRow:
    return LibraryItemRow(
        jellyfin_id=jid,
        title=title,
        overview="Overview.",
        production_year=2020,
        genres=["Drama"],
        tags=[],
        studios=[],
        community_rating=7.0,
        people=[],
        content_hash="hash",
        synced_at=_NOW,
    )


def _make_service(
    *,
    ollama: AsyncMock | None = None,
    vec_repo: AsyncMock | None = None,
    permissions: AsyncMock | None = None,
    library: AsyncMock | None = None,
    overfetch: int = 3,
) -> SearchService:
    """Build a SearchService with mocked dependencies.

    Pass pre-configured mocks to override defaults.  Mocks created
    here have safe, non-interfering defaults.
    """
    if ollama is None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()
    if vec_repo is None:
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = []
    if permissions is None:
        permissions = AsyncMock()
        permissions.filter_permitted.return_value = []
    if library is None:
        library = AsyncMock()
        library.get_many.return_value = []
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

    return SearchService(
        ollama_client=ollama,
        vec_repo=vec_repo,
        permission_service=permissions,
        library_store=library,
        overfetch_multiplier=overfetch,
    )


class TestSearchPrependsQueryPrefix:
    async def test_embed_called_with_search_query_prefix(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = []

        library = AsyncMock()
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        service = _make_service(ollama=ollama, vec_repo=vec_repo, library=library)
        await service.search("funny movie", limit=10, user_id="u1", token="tok")

        ollama.embed.assert_awaited_once()
        call_text = ollama.embed.call_args[0][0]
        assert call_text.startswith("search_query: ")
        assert "funny movie" in call_text


class TestSearchAppliesOverfetchMultiplier:
    async def test_vec_search_uses_limit_times_multiplier(self) -> None:
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = []

        library = AsyncMock()
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        service = _make_service(vec_repo=vec_repo, library=library, overfetch=3)
        await service.search("test", limit=5, user_id="u1", token="tok")

        vec_repo.search.assert_awaited_once()
        _, kwargs = vec_repo.search.call_args
        assert kwargs.get("limit") == 15  # 5 * 3


class TestSearchEnrichesWithMetadata:
    async def test_results_have_metadata_fields(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [_make_search_result("m1", 0.8)]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [
            _make_library_item("m1", "Galaxy Quest"),
        ]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
        )
        result = await service.search("test", limit=10, user_id="u1", token="tok")

        assert len(result.results) == 1
        item = result.results[0]
        assert item.title == "Galaxy Quest"
        assert item.genres == ["Drama"]
        assert item.year == 2020
        assert item.poster_url == "/Items/m1/Images/Primary"
        assert item.score == 0.8


class TestSearchTruncatesToLimit:
    async def test_no_more_than_limit_results(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [
            _make_search_result(f"m{i}", 0.9 - i * 0.1) for i in range(6)
        ]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = [f"m{i}" for i in range(6)]

        library = AsyncMock()
        library.get_many.return_value = [
            _make_library_item(f"m{i}")
            for i in range(3)  # only 3 requested
        ]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
        )
        result = await service.search("test", limit=3, user_id="u1", token="tok")

        assert len(result.results) <= 3


class TestSearchNoEmbeddingsStatus:
    async def test_returns_no_embeddings_and_empty_results(self) -> None:
        ollama = AsyncMock()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 0  # no embeddings

        library = AsyncMock()
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        service = _make_service(ollama=ollama, vec_repo=vec_repo, library=library)
        result = await service.search("test", limit=10, user_id="u1", token="tok")

        assert result.status == "no_embeddings"
        assert result.results == []
        assert result.total_candidates == 0
        assert result.filtered_count == 0
        # Ollama should NOT have been called
        ollama.embed.assert_not_awaited()


class TestSearchPartialEmbeddingsStatus:
    async def test_returns_partial_when_queue_has_pending(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 50  # some embeddings exist
        vec_repo.search.return_value = [_make_search_result("m1")]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [_make_library_item("m1")]
        library.get_queue_counts.return_value = {
            "pending": 5,
            "processing": 0,
            "failed": 0,
        }

        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
        )
        result = await service.search("test", limit=10, user_id="u1", token="tok")

        assert result.status == "partial_embeddings"
        assert len(result.results) == 1  # results still returned


class TestSearchOkStatus:
    async def test_returns_ok_when_fully_embedded(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [_make_search_result("m1")]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [_make_library_item("m1")]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
        )
        result = await service.search("test", limit=10, user_id="u1", token="tok")

        assert result.status == "ok"


class TestSearchResponseMetadata:
    async def test_response_includes_metadata_fields(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = _make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            _make_search_result("m1", 0.9),
            _make_search_result("m2", 0.8),
            _make_search_result("m3", 0.7),
        ]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1", "m3"]  # m2 filtered

        library = AsyncMock()
        library.get_many.return_value = [
            _make_library_item("m1"),
            _make_library_item("m3"),
        ]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
        )
        result = await service.search("test", limit=10, user_id="u1", token="tok")

        assert result.total_candidates == 3
        assert result.filtered_count == 1
        assert isinstance(result.query_time_ms, int)
        assert result.query_time_ms >= 0
