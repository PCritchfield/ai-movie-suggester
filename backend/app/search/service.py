"""Search service — orchestrates embed → vector search → filter → enrich."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.ollama.errors import OllamaConnectionError, OllamaError, OllamaTimeoutError
from app.search.models import (
    QUERY_PREFIX,
    SearchResponse,
    SearchResultItem,
    SearchStatus,
    SearchUnavailableError,
)

if TYPE_CHECKING:
    from app.library.store import LibraryStore
    from app.ollama.client import OllamaEmbeddingClient
    from app.permissions.service import PermissionService
    from app.vectors.repository import SqliteVecRepository

logger = logging.getLogger(__name__)


class SearchService:
    """Orchestrates the semantic search pipeline.

    Pipeline: embed query → vector search → permission filter → metadata enrich.
    """

    def __init__(
        self,
        ollama_client: OllamaEmbeddingClient,
        vec_repo: SqliteVecRepository,
        permission_service: PermissionService,
        library_store: LibraryStore,
        overfetch_multiplier: int = 3,
    ) -> None:
        self._ollama = ollama_client
        self._vec_repo = vec_repo
        self._permissions = permission_service
        self._library = library_store
        self._overfetch = overfetch_multiplier

    async def search(
        self,
        query: str,
        limit: int,
        user_id: str,
        token: str,
    ) -> SearchResponse:
        """Execute the full search pipeline.

        Args:
            query: Natural-language search query.
            limit: Maximum number of results to return.
            user_id: Jellyfin user ID for permission filtering.
            token: Decrypted Jellyfin access token.

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

        try:
            embedding_result = await self._ollama.embed(QUERY_PREFIX + query)
        except (OllamaTimeoutError, OllamaConnectionError) as exc:
            raise SearchUnavailableError(
                "Embedding service is unavailable"
            ) from exc
        except OllamaError as exc:
            raise SearchUnavailableError(
                "Embedding service returned an error"
            ) from exc

        # Over-fetch to compensate for items removed by permission filtering
        fetch_limit = limit * self._overfetch
        candidates = await self._vec_repo.search(
            embedding_result.vector, limit=fetch_limit
        )
        total_candidates = len(candidates)

        candidate_ids = [c.jellyfin_id for c in candidates]
        permitted_ids = await self._permissions.filter_permitted(
            user_id, token, candidate_ids
        )
        filtered_count = total_candidates - len(permitted_ids)
        permitted_ids = permitted_ids[:limit]

        score_map = {c.jellyfin_id: c.score for c in candidates}

        items = await self._library.get_many(permitted_ids)
        item_map = {item.jellyfin_id: item for item in items}

        results: list[SearchResultItem] = []
        for jid in permitted_ids:
            item = item_map.get(jid)
            if item is None:
                continue
            results.append(
                SearchResultItem(
                    jellyfin_id=jid,
                    title=item.title,
                    overview=item.overview,
                    genres=item.genres,
                    year=item.production_year,
                    score=score_map.get(jid, 0.0),
                    poster_url=f"/Items/{jid}/Images/Primary",
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

    async def _determine_status(self) -> SearchStatus:
        """Check embedding completeness and return status."""
        vec_count = await self._vec_repo.count()
        if vec_count == 0:
            return SearchStatus.NO_EMBEDDINGS

        queue_counts = await self._library.get_queue_counts()
        if queue_counts.get("pending", 0) > 0 or queue_counts.get("processing", 0) > 0:
            return SearchStatus.PARTIAL_EMBEDDINGS

        return SearchStatus.OK
