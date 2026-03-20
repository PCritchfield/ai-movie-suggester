"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal

import httpx
from fastapi import FastAPI

from app.config import Settings
from app.logging_config import configure_logging
from app.models import EmbeddingsStatus, HealthResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

settings = Settings()  # type: ignore[call-arg]  # env vars populate required fields
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


async def _check_jellyfin(client: httpx.AsyncClient) -> Literal["ok", "error"]:
    """Ping Jellyfin /health. Returns 'ok' or 'error'."""
    try:
        resp = await client.get(f"{settings.jellyfin_url}/health", timeout=3.0)
        return "ok" if resp.status_code == 200 else "error"
    except Exception:
        return "error"


async def _check_ollama(client: httpx.AsyncClient) -> Literal["ok", "error"]:
    """Ping Ollama /api/tags. Returns 'ok' or 'error'."""
    try:
        resp = await client.get(f"{settings.ollama_host}/api/tags", timeout=3.0)
        return "ok" if resp.status_code == 200 else "error"
    except Exception:
        return "error"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: log config, check connectivity. Shutdown: clean up."""
    logger.info("starting ai-movie-suggester backend")
    async with httpx.AsyncClient() as client:
        jf = await _check_jellyfin(client)
        ol = await _check_ollama(client)
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
        jf = await _check_jellyfin(client)
        ol = await _check_ollama(client)
    return HealthResponse(
        jellyfin=jf,
        ollama=ol,
        embeddings=EmbeddingsStatus(total=0, pending=0),
    )
