"""Unit tests for SearchService."""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.search.person_index import PersonIndex
from app.search.service import SearchService
from tests.factories import make_embedding_result, make_library_item, make_search_result


def _make_service(
    *,
    ollama: AsyncMock | None = None,
    vec_repo: AsyncMock | None = None,
    permissions: AsyncMock | None = None,
    library: AsyncMock | None = None,
    overfetch: int = 5,
    person_index: PersonIndex | None = None,
    intent_filter_person_enabled: bool = True,
    intent_filter_year_enabled: bool = True,
    intent_filter_rating_enabled: bool = True,
    rewriter: AsyncMock | None = None,
    foreign_film_home_countries: list[str] | None = None,
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
        library.search_filtered_ids = AsyncMock(return_value=None)

    return SearchService(
        ollama_client=ollama,
        vec_repo=vec_repo,
        permission_service=permissions,
        library_store=library,
        overfetch_multiplier=overfetch,
        person_index=person_index,
        intent_filter_person_enabled=intent_filter_person_enabled,
        intent_filter_year_enabled=intent_filter_year_enabled,
        intent_filter_rating_enabled=intent_filter_rating_enabled,
        rewriter=rewriter,
        foreign_film_home_countries=foreign_film_home_countries,
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


class TestSearchPipelineWithIntent:
    """Spec 24 Unit 4 — pre-filter routing tests."""

    async def test_search_pipeline_uses_filter_when_intent_present(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            make_search_result("m-em", 0.9),
            make_search_result("m-other", 0.8),
        ]
        permissions = AsyncMock()
        permissions.filter_permitted.side_effect = lambda *a, **k: a[2]
        library = AsyncMock()
        library.get_many.return_value = [
            make_library_item("m-em", "Beverly Hills Cop"),
        ]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }
        library.search_filtered_ids = AsyncMock(return_value={"m-em"})

        index = PersonIndex(names=frozenset({"eddie murphy"}))
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
        )
        result = await service.search(
            "Eddie Murphy films", limit=10, user_id="u1", token="tok"
        )

        # Filter was consulted with the matched person
        library.search_filtered_ids.assert_awaited_once()
        kwargs = library.search_filtered_ids.call_args.kwargs
        assert kwargs.get("people") == ["eddie murphy"]
        # Only the matched candidate survived the pre-filter intersection
        assert [r.jellyfin_id for r in result.results] == ["m-em"]

    async def test_filter_active_expands_fetch_limit_to_library_size(self) -> None:
        """Spec 24 / live-deploy recall fix.

        When a structured filter is active, the cosine fetch window must
        widen to the full library size so filter-matched items that don't
        rank in the default top-N can still surface. Without this, the
        post-cosine intersection silently empties out for queries whose
        embedding doesn't naturally rank the filter set highly.
        """
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 1805  # full live library size
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
        library.search_filtered_ids = AsyncMock(return_value={"jf-bw"})

        index = PersonIndex(names=frozenset({"bruce willis"}))
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
            overfetch=5,
        )
        await service.search(
            "movies starring Bruce Willis", limit=10, user_id="u1", token="tok"
        )
        # Filter active → fetch_limit must reach the full library size,
        # NOT the default limit×overfetch=50.
        vec_repo.search.assert_awaited_once()
        assert vec_repo.search.call_args.kwargs["limit"] == 1805

    async def test_filter_inactive_keeps_default_fetch_limit(self) -> None:
        """Sanity check: without a filter, fetch_limit stays at limit×overfetch."""
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 1805
        vec_repo.search.return_value = []
        library = AsyncMock()
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }
        library.search_filtered_ids = AsyncMock(return_value=None)
        index = PersonIndex(names=frozenset())
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            library=library,
            person_index=index,
            overfetch=5,
        )
        await service.search("anything", limit=10, user_id="u1", token="tok")
        assert vec_repo.search.call_args.kwargs["limit"] == 50

    async def test_search_pipeline_skips_filter_when_intent_empty(self) -> None:
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
        library.search_filtered_ids = AsyncMock()

        # Empty PersonIndex; query has no era / rating signals either
        index = PersonIndex(names=frozenset())
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
        )
        await service.search("ok", limit=10, user_id="u1", token="tok")

        library.search_filtered_ids.assert_not_awaited()

    async def test_search_pipeline_returns_empty_response_on_over_constrained_intent(
        self,
    ) -> None:
        """Q3-D contract: an over-constrained intent (e.g. nonexistent person
        + impossible year) returns an empty SearchResponse, not an exception."""
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = []
        permissions = AsyncMock()
        library = AsyncMock()
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }
        # Filter says: nothing matches your AND-intersection
        library.search_filtered_ids = AsyncMock(return_value=set())

        index = PersonIndex(names=frozenset({"eddie murphy"}))
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
        )
        resp = await service.search(
            "Eddie Murphy films", limit=10, user_id="u1", token="tok"
        )

        assert resp.results == []
        assert resp.filtered_count == 0
        # Cosine search wasn't called because the pre-filter already returned empty
        vec_repo.search.assert_not_awaited()

    async def test_intent_filter_person_disabled_bypasses_person_filter(
        self,
    ) -> None:
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
        library.search_filtered_ids = AsyncMock(return_value=None)

        index = PersonIndex(names=frozenset({"eddie murphy"}))
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
            intent_filter_person_enabled=False,
        )
        await service.search("Eddie Murphy films", limit=10, user_id="u1", token="tok")

        # Detected person, but the flag is off → people not passed to filter
        if library.search_filtered_ids.await_count:
            kwargs = library.search_filtered_ids.call_args.kwargs
            assert kwargs.get("people") in (None, [])
        # Cosine still ran (we're falling through to raw cosine)
        vec_repo.search.assert_awaited_once()


class TestSearchPipelineCountryFilter:
    """Spec 25 — country dimension wiring through the search pipeline.

    Pins three invariants:
    1. ``intent.countries`` reaches ``search_filtered_ids`` with the right
       shape (4.11).
    2. Country filter active → fetch window expands to the full library
       size, mirroring the Spec 24 person-filter recall fix (4.15).
    3. Rewriter-derived country signals survive end-to-end so a
       paraphrastic query that the LLM rewrote to a country phrase still
       routes through the structured country filter (4.16).
    """

    async def test_country_intent_passes_country_to_filter(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [make_search_result("m-jp", 0.9)]
        permissions = AsyncMock()
        permissions.filter_permitted.side_effect = lambda *a, **k: a[2]
        library = AsyncMock()
        library.get_many.return_value = [make_library_item("m-jp", "Spirited Away")]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }
        library.search_filtered_ids = AsyncMock(return_value={"m-jp"})

        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=PersonIndex(names=frozenset()),
        )
        await service.search("movies from Japan", limit=10, user_id="u1", token="tok")

        library.search_filtered_ids.assert_awaited_once()
        kwargs = library.search_filtered_ids.call_args.kwargs
        assert kwargs.get("countries") == ["JP"]
        assert kwargs.get("countries_negate") is False

    async def test_foreign_film_passes_negation_to_filter(self) -> None:
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
        library.search_filtered_ids = AsyncMock(return_value=set())

        service = _make_service(
            library=library,
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            person_index=PersonIndex(names=frozenset()),
            foreign_film_home_countries=["US", "GB"],
        )
        await service.search("foreign film", limit=10, user_id="u1", token="tok")

        library.search_filtered_ids.assert_awaited_once()
        kwargs = library.search_filtered_ids.call_args.kwargs
        assert kwargs.get("countries") == ["US", "GB"]
        assert kwargs.get("countries_negate") is True

    async def test_country_filter_expands_fetch_limit_to_library_size(self) -> None:
        """Spec 25 — country dimension inherits the Spec 24 filter-aware-fetch
        recall fix.

        With a country filter narrowing to a small subset of a 1805-item
        library, the cosine fetch window must widen to the full library
        size so all country-matched items have a chance to surface in the
        top-N. Without this, country-narrowed queries would silently lose
        recall when the filter set sat below the default cosine top-N.
        """
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 1805  # full live library size
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
        library.search_filtered_ids = AsyncMock(return_value={"jf-jp-1"})

        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=PersonIndex(names=frozenset()),
            overfetch=5,
        )
        await service.search("movies from Japan", limit=10, user_id="u1", token="tok")

        vec_repo.search.assert_awaited_once()
        # Country filter active ⇒ fetch_limit reaches full library size,
        # NOT the default limit×overfetch=50.
        assert vec_repo.search.call_args.kwargs["limit"] == 1805

    async def test_rewriter_country_signal_survives_to_filter(self) -> None:
        """Spec 25 — rewriter pass-through.

        Original query is paraphrastic with no signals; the rewriter
        produces a country-bearing rewrite (e.g. ``"a Japanese
        animation"``); the SearchService re-detects intent on the
        rewrite, surfaces a country signal, and passes it into
        ``search_filtered_ids``. Pins that the structurally-extracted
        country signal isn't dropped on the rewrite branch — the country
        dimension must work end-to-end whether the signal arrived in the
        raw query or via the LLM rewrite.
        """
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 1805
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
        library.search_filtered_ids = AsyncMock(return_value={"jf-jp-1"})

        rewriter = AsyncMock()
        rewriter.rewrite = AsyncMock(return_value="Japanese animation")

        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=PersonIndex(names=frozenset()),
            rewriter=rewriter,
        )
        # 4-word paraphrastic query with no structural signals
        await service.search(
            "an evocative dreamlike film",
            limit=10,
            user_id="u1",
            token="tok",
        )

        rewriter.rewrite.assert_awaited_once()
        # The rewritten "Japanese animation" must trigger the country
        # filter — not get dropped because the signal arrived after rewrite.
        library.search_filtered_ids.assert_awaited_once()
        kwargs = library.search_filtered_ids.call_args.kwargs
        assert kwargs.get("countries") == ["JP"]


class TestSearchPipelineRewriterGating:
    """Spec 24 Unit 5 — paraphrastic rewriter is invoked ONLY when intent
    has no structured signal AND the query is paraphrastic."""

    async def test_rewriter_not_invoked_for_signal_query(self) -> None:
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
        library.search_filtered_ids = AsyncMock(return_value={"x"})

        rewriter = AsyncMock()
        index = PersonIndex(names=frozenset({"eddie murphy"}))
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
            rewriter=rewriter,
        )

        await service.search("Eddie Murphy films", limit=10, user_id="u1", token="tok")
        rewriter.rewrite.assert_not_awaited()

    async def test_rewriter_invoked_for_paraphrastic_query(self) -> None:
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
        library.search_filtered_ids = AsyncMock(return_value=None)

        rewriter = AsyncMock()
        rewriter.rewrite = AsyncMock(return_value="rewritten short paraphrase")
        index = PersonIndex(names=frozenset())
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
            rewriter=rewriter,
        )

        await service.search(
            "something like alien but funny and uplifting",
            limit=10,
            user_id="u1",
            token="tok",
        )
        rewriter.rewrite.assert_awaited_once()
        # The rewrite must be the string passed to the embedder
        ollama.embed.assert_awaited_once()
        embed_input = ollama.embed.call_args.args[0]
        assert "rewritten short paraphrase" in embed_input


class TestSearchSkipsPermissionFilterWhenEmpty:
    """Spec 24 / Copilot #8 — short-circuit ``filter_permitted([])``.

    With a real ``PermissionService`` the empty-list call still triggers a
    Jellyfin permission fetch on cache miss. Skipping it avoids that
    round-trip when the prior filter steps already produced no survivors.
    """

    async def test_no_permission_call_when_exclude_drains_all(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            make_search_result("watched-1", 0.9),
            make_search_result("watched-2", 0.8),
        ]
        permissions = AsyncMock()
        library = AsyncMock()
        library.get_many.return_value = []
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
        # exclude_ids removes every cosine result, so candidate_ids = [].
        await service.search(
            "test",
            limit=10,
            user_id="u1",
            token="tok",
            exclude_ids={"watched-1", "watched-2"},
        )
        permissions.filter_permitted.assert_not_awaited()

    async def test_no_permission_call_when_filter_drops_all(self) -> None:
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            make_search_result("m-other", 0.9),
        ]
        permissions = AsyncMock()
        library = AsyncMock()
        library.get_many.return_value = []
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }
        # Pre-filter narrows to an id the cosine search did NOT surface,
        # so the post-cosine intersection produces an empty list.
        library.search_filtered_ids = AsyncMock(return_value={"m-not-in-cosine"})
        index = PersonIndex(names=frozenset({"eddie murphy"}))
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
        )
        await service.search("Eddie Murphy films", limit=10, user_id="u1", token="tok")
        permissions.filter_permitted.assert_not_awaited()


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

    async def test_filtered_count_excludes_pre_filter_drops(self) -> None:
        """``filtered_count`` reports permission drops only — not items
        removed by the structured pre-filter or exclude_ids (Copilot #2).
        """
        ollama = AsyncMock()
        ollama.embed.return_value = make_embedding_result()
        vec_repo = AsyncMock()
        vec_repo.count.return_value = 100
        vec_repo.search.return_value = [
            make_search_result("keep", 0.9),
            make_search_result("drop_by_filter_a", 0.8),
            make_search_result("drop_by_filter_b", 0.7),
        ]
        permissions = AsyncMock()
        # The single survivor of the pre-filter is also permitted.
        permissions.filter_permitted.return_value = ["keep"]
        library = AsyncMock()
        library.get_many.return_value = [make_library_item("keep")]
        library.get_queue_counts.return_value = {
            "pending": 0,
            "processing": 0,
            "failed": 0,
        }
        # Pre-filter narrows {keep, drop_by_filter_a, drop_by_filter_b} → {keep}.
        library.search_filtered_ids = AsyncMock(return_value={"keep"})
        index = PersonIndex(names=frozenset({"eddie murphy"}))
        service = _make_service(
            ollama=ollama,
            vec_repo=vec_repo,
            permissions=permissions,
            library=library,
            person_index=index,
        )
        result = await service.search(
            "Eddie Murphy films", limit=10, user_id="u1", token="tok"
        )
        # Two items were removed by the pre-filter, ZERO by permissions.
        assert result.filtered_count == 0
        # total_candidates still reports the raw vector-search count.
        assert result.total_candidates == 3
