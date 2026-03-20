"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI

from app.config import Settings
from app.logging_config import configure_logging
from app.models import EmbeddingsStatus, HealthResponse, ServiceStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

settings = Settings()  # type: ignore[call-arg]  # env vars populate required fields
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


async def _check_service(client: httpx.AsyncClient, url: str) -> ServiceStatus:
    """Ping a service URL. Returns 'ok' or 'error'."""
    try:
        resp = await client.get(url, timeout=3.0)
        return "ok" if resp.status_code == 200 else "error"
    except Exception:
        logger.debug("service check failed url=%s", url, exc_info=True)
        return "error"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: log config, check connectivity. Shutdown: clean up."""
    logger.info("starting ai-movie-suggester backend")
    async with httpx.AsyncClient() as client:
        jf, ol = await asyncio.gather(
            _check_service(client, f"{settings.jellyfin_url}/health"),
            _check_service(client, f"{settings.ollama_host}/api/tags"),
        )
    logger.info("startup checks: jellyfin=%s ollama=%s", jf, ol)
    if jf == "error":
        logger.warning("jellyfin not reachable at startup")
    if ol == "error":
        logger.warning("ollama not reachable at startup")
    yield
    logger.info("shutting down ai-movie-suggester backend")


app = FastAPI(title="ai-movie-suggester", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Service health: checks Jellyfin and Ollama connectivity."""
    async with httpx.AsyncClient() as client:
        jf, ol = await asyncio.gather(
            _check_service(client, f"{settings.jellyfin_url}/health"),
            _check_service(client, f"{settings.ollama_host}/api/tags"),
        )
    return HealthResponse(
        jellyfin=jf,
        ollama=ol,
        embeddings=EmbeddingsStatus(total=0, pending=0),
    )
