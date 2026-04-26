"""Unit tests for SearchService."""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.search.service import SearchService
from tests.factories import make_embedding_result, make_library_item, make_search_result


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
        ollama.embed.return_value = make_embedding_result()
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
        ollama.embed.return_value = make_embedding_result()

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

    async def test_default_overfetch_is_5(self) -> None:
        """Default multiplier bumped 3 → 5 in v5 to give the genre rerank
        more headroom to find tier-1 matches at lower cosine ranks."""
        from app.search.service import SearchService

        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = []
        permissions = AsyncMock()
        permissions.filter_permitted.return_value = []
        library = AsyncMock()
        library.get_many.return_value = []
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }

        service = SearchService(
            ollama_client=ollama,
            vec_repo=vec_repo,
            permission_service=permissions,
            library_store=library,
        )
        await service.search("test", limit=10, user_id="u1", token="tok")

        _, kwargs = vec_repo.search.call_args
        assert kwargs.get("limit") == 50  # 10 * 5


class TestSearchEnrichesWithMetadata:
    async def test_results_have_metadata_fields(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [make_search_result("m1", 0.8)]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item("m1", "Galaxy Quest"),
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
        assert item.poster_url == "/api/images/m1"
        assert item.score == 0.8
        assert item.community_rating == 7.0
        assert item.runtime_minutes == 120


class TestSearchTruncatesToLimit:
    async def test_no_more_than_limit_results(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [
            make_search_result(f"m{i}", 0.9 - i * 0.1) for i in range(6)
        ]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = [f"m{i}" for i in range(6)]

        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item(f"m{i}")
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
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 50  # some embeddings exist
        vec_repo.search.return_value = [make_search_result("m1")]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [make_library_item("m1")]
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
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [make_search_result("m1")]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [make_library_item("m1")]
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


class TestSearchJellyfinWebUrl:
    async def test_jellyfin_web_url_populated_when_configured(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [make_search_result("m1", 0.8)]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [make_library_item("m1")]
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
        service._jellyfin_web_url = "https://jellyfin.example.com"
        result = await service.search("test", limit=10, user_id="u1", token="tok")

        assert len(result.results) == 1
        assert (
            result.results[0].jellyfin_web_url
            == "https://jellyfin.example.com/web/#!/details?id=m1"
        )

    async def test_jellyfin_web_url_none_when_not_configured(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [make_search_result("m1", 0.8)]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [make_library_item("m1")]
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
        # No jellyfin_web_url set (default None)
        result = await service.search("test", limit=10, user_id="u1", token="tok")

        assert len(result.results) == 1
        assert result.results[0].jellyfin_web_url is None


class TestSearchExcludeIds:
    async def test_search_excludes_watched_ids(self) -> None:
        """Items in exclude_ids are removed from results."""
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [
            make_search_result("m1", 0.9),
            make_search_result("m2", 0.8),
            make_search_result("m3", 0.7),
        ]

        permissions = AsyncMock()
        # Only m1 and m3 survive (m2 excluded before permission check)
        permissions.filter_permitted.return_value = ["m1", "m3"]

        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item("m1"),
            make_library_item("m3"),
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
        result = await service.search(
            "test", limit=10, user_id="u1", token="tok", exclude_ids={"m2"}
        )

        # m2 should not appear in results
        result_ids = {r.jellyfin_id for r in result.results}
        assert "m2" not in result_ids
        assert "m1" in result_ids
        assert "m3" in result_ids

        # m2 should not have been sent to permission filtering
        candidate_ids = permissions.filter_permitted.call_args[0][2]
        assert "m2" not in candidate_ids

    async def test_search_exclude_ids_none_preserves_behavior(self) -> None:
        """Passing exclude_ids=None behaves identically to no exclusion."""
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [
            make_search_result("m1", 0.9),
            make_search_result("m2", 0.8),
        ]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1", "m2"]

        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item("m1"),
            make_library_item("m2"),
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
        result = await service.search(
            "test", limit=10, user_id="u1", token="tok", exclude_ids=None
        )

        assert len(result.results) == 2
        candidate_ids = permissions.filter_permitted.call_args[0][2]
        assert "m1" in candidate_ids
        assert "m2" in candidate_ids

    async def test_search_exclude_ids_empty_set_preserves_behavior(self) -> None:
        """Passing exclude_ids=set() behaves identically to no exclusion."""
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 10
        vec_repo.search.return_value = [
            make_search_result("m1", 0.9),
        ]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1"]

        library = AsyncMock()
        library.get_many.return_value = [make_library_item("m1")]
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
        result = await service.search(
            "test", limit=10, user_id="u1", token="tok", exclude_ids=set()
        )

        assert len(result.results) == 1
        candidate_ids = permissions.filter_permitted.call_args[0][2]
        assert "m1" in candidate_ids


class TestGenreRerank:
    """v5 — when the query mentions a genre, candidates whose genres match
    are bucket-sorted to the top of the result set, preserving cosine
    order within each tier. Without genre keywords in the query, behaviour
    is unchanged."""

    async def test_rerank_bumps_genre_match_above_non_match(self) -> None:
        """Cosine order: m1 (highest), m2, m3. Genre tags:
        - m1 = ['Comedy']                    (matches comedy only)
        - m2 = ['Comedy', 'Science Fiction'] (matches both — tier 1)
        - m3 = ['Action']                    (matches none — tier 3)
        Query 'sci-fi comedy' → output order should be m2, m1, m3.
        """
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            make_search_result("m1", 0.90),
            make_search_result("m2", 0.80),
            make_search_result("m3", 0.70),
        ]
        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1", "m2", "m3"]
        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item("m1", title="Stand-Up Special", genres=["Comedy"]),
            make_library_item(
                "m2", title="Galaxy Quest", genres=["Comedy", "Science Fiction"]
            ),
            make_library_item("m3", title="Die Hard", genres=["Action"]),
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
        result = await service.search(
            "sci-fi comedy", limit=10, user_id="u1", token="tok"
        )

        ids = [r.jellyfin_id for r in result.results]
        assert ids == ["m2", "m1", "m3"]

    async def test_no_genre_keyword_preserves_cosine_order(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            make_search_result("m1", 0.90),
            make_search_result("m2", 0.80),
            make_search_result("m3", 0.70),
        ]
        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1", "m2", "m3"]
        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item("m1", genres=["Comedy"]),
            make_library_item("m2", genres=["Comedy", "Science Fiction"]),
            make_library_item("m3", genres=["Action"]),
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
        # Query with no detectable genre keyword — order untouched
        result = await service.search(
            "something good", limit=10, user_id="u1", token="tok"
        )

        ids = [r.jellyfin_id for r in result.results]
        assert ids == ["m1", "m2", "m3"]

    async def test_rerank_preserves_cosine_order_within_tier(self) -> None:
        """Two candidates in tier 1 (both match all detected genres);
        their relative order should be by cosine score (highest first)."""
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            # Higher cosine but only matches one genre
            make_search_result("standup", 0.95),
            # Lower cosine, matches both — should still come above standup
            make_search_result("galaxy_quest", 0.70),
            # Even lower, matches both — third
            make_search_result("evolution", 0.60),
        ]
        permissions = AsyncMock()
        permissions.filter_permitted.return_value = [
            "standup",
            "galaxy_quest",
            "evolution",
        ]
        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item("standup", genres=["Comedy"]),
            make_library_item("galaxy_quest", genres=["Comedy", "Science Fiction"]),
            make_library_item("evolution", genres=["Comedy", "Science Fiction"]),
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
        result = await service.search(
            "sci-fi comedy", limit=10, user_id="u1", token="tok"
        )

        ids = [r.jellyfin_id for r in result.results]
        # tier 1 (galaxy_quest, evolution by cosine), then tier 2 (standup)
        assert ids == ["galaxy_quest", "evolution", "standup"]


class TestSearchResponseMetadata:
    async def test_response_includes_metadata_fields(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()

        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            make_search_result("m1", 0.9),
            make_search_result("m2", 0.8),
            make_search_result("m3", 0.7),
        ]

        permissions = AsyncMock()
        permissions.filter_permitted.return_value = ["m1", "m3"]  # m2 filtered

        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item("m1"),
            make_library_item("m3"),
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
