"""Search service — orchestrates embed → vector search → filter → enrich."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.ollama.errors import OllamaConnectionError, OllamaError, OllamaTimeoutError
from app.search.genre_keywords import detect_query_genres
from app.search.intent import QueryIntent, detect_intent
from app.search.models import (
    QUERY_PREFIX,
    SearchResponse,
    SearchResultItem,
    SearchStatus,
    SearchUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from app.library.models import LibraryItemRow
    from app.library.store import LibraryStore
    from app.ollama.client import OllamaEmbeddingClient
    from app.permissions.service import PermissionService
    from app.search.person_index import PersonIndex
    from app.search.rewriter import QueryRewriter
    from app.vectors.repository import SqliteVecRepository

logger = logging.getLogger(__name__)


class SearchService:
    """Orchestrates the semantic search pipeline.

    Pipeline (Spec 24): detect_intent → optional structured pre-filter →
    embed query → vector search → permission filter → metadata enrich →
    soft genre rerank.
    """

    def __init__(
        self,
        ollama_client: OllamaEmbeddingClient,
        vec_repo: SqliteVecRepository,
        permission_service: PermissionService,
        library_store: LibraryStore,
        overfetch_multiplier: int = 5,
        jellyfin_web_url: str | None = None,
        person_index: PersonIndex | None = None,
        intent_filter_person_enabled: bool = True,
        intent_filter_year_enabled: bool = True,
        intent_filter_rating_enabled: bool = True,
        rewriter: QueryRewriter | None = None,
    ) -> None:
        self._ollama = ollama_client
        self._vec_repo = vec_repo
        self._permissions = permission_service
        self._library = library_store
        self._overfetch = overfetch_multiplier
        self._jellyfin_web_url = (
            jellyfin_web_url.rstrip("/") if jellyfin_web_url else None
        )
        self._person_index = person_index
        self._filter_person = intent_filter_person_enabled
        self._filter_year = intent_filter_year_enabled
        self._filter_rating = intent_filter_rating_enabled
        self._rewriter = rewriter
        self._status_cache: SearchStatus | None = None
        self._status_cache_time: float = 0.0
        self._status_cache_ttl: float = 30.0  # seconds

    @property
    def person_index(self) -> PersonIndex | None:
        """Read-only handle to the injected ``PersonIndex`` (or ``None``).

        Exposed so tests and the eval harness can introspect routing
        configuration without reaching into private state.
        """
        return self._person_index

    async def search(
        self,
        query: str,
        limit: int,
        user_id: str,
        token: str,
        exclude_ids: set[str] | None = None,
    ) -> SearchResponse:
        """Execute the full search pipeline.

        Args:
            query: Natural-language search query.
            limit: Maximum number of results to return.
            user_id: Jellyfin user ID for permission filtering.
            token: Decrypted Jellyfin access token.
            exclude_ids: Optional set of Jellyfin item IDs to exclude
                from results (e.g. already-watched items).

        Returns:
            SearchResponse with results, metadata, and status.

        Raises:
            SearchUnavailableError: If Ollama is unreachable.
        """
        t0 = time.perf_counter()

        status = await self._determine_status()
        if status == SearchStatus.NO_EMBEDDINGS:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return SearchResponse(
                status=SearchStatus.NO_EMBEDDINGS,
                results=[],
                total_candidates=0,
                filtered_count=0,
                query_time_ms=elapsed_ms,
            )

        # Spec 24: detect intent and (optionally) pre-filter the candidate set
        # before cosine. ``filter_ids`` is None when no filter applied — caller
        # falls through to full vec0; an empty set means AND-empty (Q3-D contract).
        # On a paraphrastic miss we rewrite the query and re-feed through the
        # intent layer (Q4-C default-on). ``effective_intent`` carries the
        # detected genre groups through to ``_rerank_by_genre`` so we don't
        # call ``detect_query_genres`` twice per request.
        effective_query, filter_ids, effective_intent = await self._route_query(query)
        if filter_ids is not None and len(filter_ids) == 0:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "search_filter_empty query_len=%d ms=%d",
                len(query),
                elapsed_ms,
            )
            return SearchResponse(
                status=status,
                results=[],
                total_candidates=0,
                filtered_count=0,
                query_time_ms=elapsed_ms,
            )

        try:
            embedding_result = await self._ollama.embed(QUERY_PREFIX + effective_query)
        except (OllamaTimeoutError, OllamaConnectionError) as exc:
            raise SearchUnavailableError("Embedding service is unavailable") from exc
        except OllamaError as exc:
            raise SearchUnavailableError("Embedding service returned an error") from exc

        # Over-fetch to compensate for items removed by permission filtering
        # and to give the genre rerank room to find tier-1 matches at lower
        # cosine ranks.
        #
        # Spec 24 / live deploy April 2026 finding: when a structured filter
        # is active, the post-cosine intersection has a severe recall problem
        # for queries whose embedding doesn't naturally rank the filter set
        # highly. Example: "movies starring Bruce Willis" — the embeddings
        # are plot-based, not cast-based, so Bruce Willis's films can sit at
        # rank 200+ in cosine results. With the default limit×overfetch=50
        # window the intersection then drops everything and the user gets
        # an empty response despite the filter SQL having matched correctly.
        #
        # Mitigation: when ``filter_ids`` is set, expand the fetch window to
        # the full embedded library size so every filter-matched item has a
        # chance to surface. ``vec0`` cosine over ~2k items is sub-millisecond
        # and Spec 24 Task 3.7 explicitly contemplated this trade-off.
        fetch_limit = limit * self._overfetch
        if filter_ids is not None:
            fetch_limit = max(fetch_limit, await self._vec_repo.count())
        candidates = await self._vec_repo.search(
            embedding_result.vector, limit=fetch_limit
        )
        total_candidates = len(candidates)

        # Constrain cosine candidates to the structured pre-filter set.
        if filter_ids is not None:
            candidates = [c for c in candidates if c.jellyfin_id in filter_ids]

        if exclude_ids:
            candidates = [c for c in candidates if c.jellyfin_id not in exclude_ids]

        candidate_ids = [c.jellyfin_id for c in candidates]
        permitted_ids = await self._permissions.filter_permitted(
            user_id, token, candidate_ids
        )
        # ``filtered_count`` is reported back to the client as the number of
        # candidates removed by the permission filter — not by the structured
        # pre-filter or ``exclude_ids``. Compute it from the pre-permission
        # candidate count rather than ``total_candidates`` so the metadata
        # stays accurate when the router or the watch-history exclusion
        # narrowed the candidate pool first (Copilot review #2).
        filtered_count = len(candidate_ids) - len(permitted_ids)

        score_map = {c.jellyfin_id: c.score for c in candidates}

        # Fetch metadata for ALL permitted candidates (not just the top
        # ``limit``) so the genre rerank can see each candidate's genres.
        items = await self._library.get_many(permitted_ids)
        item_map = {item.jellyfin_id: item for item in items}

        # Soft genre rerank: bucket-sort by genre match while preserving
        # cosine order (the input ``permitted_ids`` order) within each tier.
        # Reuse the genre groups already computed by ``detect_intent`` if
        # available — otherwise fall back to a fresh detection so callers
        # bypassing the router (e.g. unit tests) still get the rerank.
        if effective_intent is not None and effective_intent.genres:
            genre_groups = effective_intent.genres
        else:
            genre_groups = detect_query_genres(effective_query)
        ordered_ids = self._rerank_by_genre(genre_groups, permitted_ids, item_map)
        ordered_ids = ordered_ids[:limit]

        results: list[SearchResultItem] = []
        for jid in ordered_ids:
            item = item_map.get(jid)
            if item is None:
                continue
            web_url: str | None = None
            if self._jellyfin_web_url:
                web_url = f"{self._jellyfin_web_url}/web/#!/details?id={jid}"

            results.append(
                SearchResultItem(
                    jellyfin_id=jid,
                    title=item.title,
                    overview=item.overview,
                    genres=item.genres,
                    year=item.production_year,
                    score=score_map.get(jid, 0.0),
                    poster_url=f"/api/images/{jid}",
                    community_rating=item.community_rating,
                    runtime_minutes=item.runtime_minutes,
                    jellyfin_web_url=web_url,
                )
            )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "search query_len=%d candidates=%d filtered=%d results=%d ms=%d",
            len(query),
            total_candidates,
            filtered_count,
            len(results),
            elapsed_ms,
        )

        return SearchResponse(
            status=status,
            results=results,
            total_candidates=total_candidates,
            filtered_count=filtered_count,
            query_time_ms=elapsed_ms,
        )

    async def _route_query(
        self, query: str
    ) -> tuple[str, set[str] | None, QueryIntent | None]:
        """Route the query through intent detection + optional rewriter.

        Returns ``(effective_query, filter_ids, effective_intent)``:
          - ``filter_ids`` is None when no filter applied; an empty set
            means AND-empty (Q3-D).
          - ``effective_intent`` is the intent detected against the
            *effective* query (after any rewrite), exposed so callers can
            reuse its genre groups without re-running detection.

        Routing strategy (Spec 24 Q1-B + Q4-C):
          - No PersonIndex → return (query, None, None) and skip everything.
          - Intent has a structured signal → run filter, no rewrite.
          - Intent paraphrastic AND no structured signal → rewrite, then
            re-feed through detect_intent. New signals trigger
            ``rewrite_chained_to_<signal>`` log line.
        """
        if self._person_index is None:
            return query, None, None

        intent = detect_intent(query, self._person_index)
        if intent.has_signals():
            return query, await self._apply_filter(intent), intent

        # Paraphrastic-fallback path: rewrite, re-detect intent, log chaining.
        if intent.is_paraphrastic and self._rewriter is not None:
            rewritten = await self._rewriter.rewrite(query)
            if rewritten != query:
                rewritten_intent = detect_intent(rewritten, self._person_index)
                self._log_chain(intent, rewritten_intent)
                if rewritten_intent.has_signals():
                    return (
                        rewritten,
                        await self._apply_filter(rewritten_intent),
                        rewritten_intent,
                    )
                return rewritten, None, rewritten_intent

        return query, None, intent

    async def _apply_filter(self, intent: QueryIntent) -> set[str] | None:
        """Translate an intent into a filter call respecting the per-flag
        switches; logs signal counts only (no names, no query text)."""
        people = intent.people if (self._filter_person and intent.people) else None
        year_range = (
            intent.year_range
            if (self._filter_year and intent.year_range is not None)
            else None
        )
        ratings = intent.ratings if (self._filter_rating and intent.ratings) else None

        if not people and year_range is None and not ratings:
            return None

        filter_ids = await self._library.search_filtered_ids(
            people=people, year_range=year_range, ratings=ratings
        )
        signals = [
            label
            for label, present in (
                ("person", bool(people)),
                ("year", year_range is not None),
                ("rating", bool(ratings)),
            )
            if present
        ]
        logger.info(
            "search_filtered_ids signals=%s pool_size=%d",
            signals,
            len(filter_ids) if filter_ids is not None else -1,
        )
        return filter_ids

    @staticmethod
    def _log_chain(original: QueryIntent, rewritten: QueryIntent) -> None:
        """Emit ``rewrite_chained_to_<signal>`` when the rewrite surfaces
        a structured signal the raw query did not. One log line per signal
        type (Q4-C resolution)."""
        gained = []
        if rewritten.people and not original.people:
            gained.append("person_filter")
        if rewritten.year_range is not None and original.year_range is None:
            gained.append("year_filter")
        if rewritten.ratings and not original.ratings:
            gained.append("rating_filter")
        if rewritten.genres and not original.genres:
            gained.append("genre_rerank")
        for kind in gained:
            logger.info("rewrite_chained_to_%s", kind)

    @staticmethod
    def _rerank_by_genre(
        groups: list[frozenset[str]],
        permitted_ids: list[str],
        item_map: Mapping[str, LibraryItemRow],
    ) -> list[str]:
        """Bucket-sort permitted IDs by precomputed genre match groups.

        - Tier 1: candidate genres match **every** detected genre group
        - Tier 2: matches **at least one** group
        - Tier 3: matches **none**

        Cosine order is preserved within each tier (input order is
        cosine-ordered). If ``groups`` is empty, returns ``permitted_ids``
        unchanged. The caller is responsible for genre detection so we
        don't run ``detect_query_genres`` twice per request.
        """
        if not groups:
            return permitted_ids

        tier1: list[str] = []
        tier2: list[str] = []
        tier3: list[str] = []
        for jid in permitted_ids:
            item = item_map.get(jid)
            if item is None:
                # Lost between permission filter and metadata fetch — keep
                # at the back rather than dropping outright.
                tier3.append(jid)
                continue
            item_genres = set(item.genres or [])
            matches = sum(1 for g in groups if g & item_genres)
            if matches == len(groups):
                tier1.append(jid)
            elif matches > 0:
                tier2.append(jid)
            else:
                tier3.append(jid)
        return tier1 + tier2 + tier3

    async def _determine_status(self) -> SearchStatus:
        """Check embedding completeness and return status (cached 30s)."""
        now = time.monotonic()
        if (
            self._status_cache is not None
            and (now - self._status_cache_time) < self._status_cache_ttl
        ):
            return self._status_cache

        vec_count = await self._vec_repo.count()
        if vec_count == 0:
            status = SearchStatus.NO_EMBEDDINGS
        else:
            queue_counts = await self._library.get_queue_counts()
            pending = queue_counts.get("pending", 0) > 0
            processing = queue_counts.get("processing", 0) > 0
            if pending or processing:
                status = SearchStatus.PARTIAL_EMBEDDINGS
            else:
                status = SearchStatus.OK

        self._status_cache = status
        self._status_cache_time = now
        return status
