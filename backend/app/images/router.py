"""Image proxy router — proxies Jellyfin poster images through the backend."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import Response
from slowapi import Limiter  # noqa: TC002

from app.auth.dependencies import get_current_session

if TYPE_CHECKING:
    from app.auth.models import SessionMeta
    from app.config import Settings

logger = logging.getLogger(__name__)

_ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)


def create_images_router(
    settings: Settings,
    limiter: Limiter | None = None,
) -> APIRouter:
    """Build the images APIRouter for proxying Jellyfin poster images."""
    router = APIRouter(prefix="/api", tags=["images"])
    jellyfin_base = settings.jellyfin_url.rstrip("/")
    _limit = limiter.limit("30/minute") if limiter else (lambda f: f)

    @router.get(
        "/images/{jellyfin_id}",
        responses={
            200: {"content": {"image/jpeg": {}}, "description": "Poster image"},
            401: {"description": "Not authenticated"},
            404: {"description": "No poster found"},
            422: {"description": "Invalid ID format"},
            429: {"description": "Rate limit exceeded"},
            502: {"description": "Jellyfin unreachable"},
        },
    )
    @_limit
    async def get_image(
        request: Request,
        jellyfin_id: str = Path(pattern=r"^[a-f0-9]{32}$"),  # noqa: B008
        session: SessionMeta = Depends(get_current_session),  # noqa: B008
    ) -> Response:
        """Proxy a Jellyfin poster image for the given item."""
        session_store = request.app.state.session_store
        token = await session_store.get_token(session.session_id)
        if token is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        image_url = f"{jellyfin_base}/Items/{jellyfin_id}/Images/Primary"
        http_client: httpx.AsyncClient = request.app.state.jellyfin_client._client

        try:
            resp = await http_client.get(
                image_url,
                headers={"Authorization": f'MediaBrowser Token="{token}"'},
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning("image_proxy_upstream_error id=%s", jellyfin_id)
            raise HTTPException(status_code=502, detail="Jellyfin unreachable") from exc

        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="No poster found")

        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Not authenticated")

        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Jellyfin error")

        content_type = resp.headers.get("content-type", "image/jpeg")
        if content_type not in _ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=502, detail="Unexpected content type from Jellyfin"
            )

        headers: dict[str, str] = {
            "Cache-Control": "private, max-age=86400",
        }
        if "content-length" in resp.headers:
            headers["Content-Length"] = resp.headers["content-length"]

        return Response(
            content=resp.content,
            media_type=content_type,
            headers=headers,
        )

    return router
