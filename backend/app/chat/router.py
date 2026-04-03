"""Chat API route — streaming chat over SSE."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter  # noqa: TC002

from app.auth.dependencies import get_current_session
from app.chat.models import ChatRequest  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.auth.models import SessionMeta
    from app.config import Settings

logger = logging.getLogger(__name__)


async def _sse_generator(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """Format event dicts as SSE data lines."""
    async for event in events:
        yield f"data: {json.dumps(event)}\n\n"


def create_chat_router(
    settings: Settings,
    limiter: Limiter | None = None,
) -> APIRouter:
    """Build the chat APIRouter with rate limiting from settings."""
    router = APIRouter(prefix="/api", tags=["chat"])
    _limit = (
        limiter.limit(f"{settings.chat_rate_limit}/minute")
        if limiter
        else (lambda f: f)
    )

    @router.post(
        "/chat",
        responses={
            401: {"description": "Not authenticated"},
            422: {"description": "Validation error"},
            429: {"description": "Rate limit exceeded"},
        },
    )
    @_limit
    async def chat(
        body: ChatRequest,
        request: Request,
        session: SessionMeta = Depends(get_current_session),  # noqa: B008
    ) -> StreamingResponse:
        """Chat with the movie recommendation assistant.

        Streams Server-Sent Events: metadata event first, then LLM
        text tokens, then a done or error event.
        """
        session_store = request.app.state.session_store
        token = await session_store.get_token(session.session_id)
        if token is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        service = request.app.state.chat_service

        event_stream = service.stream(
            query=body.message,
            user_id=session.user_id,
            token=token,
        )

        return StreamingResponse(
            content=_sse_generator(event_stream),
            media_type="text/event-stream",
        )

    return router
