"""Search API route — semantic search over the movie library."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter  # noqa: TC002

from app.auth.dependencies import get_current_session
from app.search.models import SearchRequest, SearchResponse, SearchUnavailableError
from app.search.service import SearchService

if TYPE_CHECKING:
    from app.auth.models import SessionMeta
    from app.config import Settings

logger = logging.getLogger(__name__)


def create_search_router(
    settings: Settings,
    limiter: Limiter | None = None,
) -> APIRouter:
    """Build the search APIRouter with rate limiting from settings."""
    router = APIRouter(prefix="/api", tags=["search"])
    _limit = (
        limiter.limit(f"{settings.search_rate_limit}/minute")
        if limiter
        else (lambda f: f)
    )

    @router.post(
        "/search",
        response_model=SearchResponse,
        responses={
            400: {"description": "Invalid query or limit"},
            401: {"description": "Not authenticated"},
            429: {"description": "Rate limit exceeded"},
            503: {"description": "Embedding service unavailable"},
        },
    )
    @_limit
    async def search(
        body: SearchRequest,
        request: Request,
        session: SessionMeta = Depends(get_current_session),  # noqa: B008
    ) -> SearchResponse:
        """Search the movie library using natural language.

        Embeds the query, searches the vector DB, filters by user
        permissions, and returns enriched metadata.
        """
        # Retrieve the user's Jellyfin token (with expiry check)
        session_store = request.app.state.session_store
        token = await session_store.get_token(session.session_id)
        if token is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Build service from app.state dependencies
        service = SearchService(
            ollama_client=request.app.state.ollama_client,
            vec_repo=request.app.state.vec_repo,
            permission_service=request.app.state.permission_service,
            library_store=request.app.state.library_store,
            overfetch_multiplier=settings.search_overfetch_multiplier,
        )

        try:
            return await service.search(
                query=body.query,
                limit=body.limit,
                user_id=session.user_id,
                token=token,
            )
        except SearchUnavailableError:
            logger.warning("search_unavailable query_len=%d", len(body.query))
            raise HTTPException(
                status_code=503,
                detail="Search unavailable: embedding service is down",
            ) from None

    return router
