"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.config import Settings
from app.logging_config import configure_logging
from app.middleware import SecurityHeadersMiddleware
from app.models import EmbeddingsStatus, HealthResponse, ServiceStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _check_service(
    client: httpx.AsyncClient, url: str, logger: logging.Logger
) -> ServiceStatus:
    """Ping a service URL. Returns 'ok' or 'error'."""
    try:
        resp = await client.get(url, timeout=3.0)
        return "ok" if resp.status_code == 200 else "error"
    except Exception:
        logger.debug("service check failed url=%s", url, exc_info=True)
        return "error"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Application settings. If None, loads from environment.

    Returns:
        Configured FastAPI application instance.
    """
    if settings is None:
        settings = Settings()  # type: ignore[call-arg]

    configure_logging(settings.log_level)
    _logger = logging.getLogger(__name__)

    # Resolve docs toggle: explicit enable_docs overrides log_level default
    if settings.enable_docs is not None:
        docs_enabled = settings.enable_docs
    else:
        docs_enabled = settings.log_level == "debug"

    _logger.info("docs_enabled=%s", docs_enabled)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Startup: log config, check connectivity. Shutdown: clean up."""
        _logger.info("starting ai-movie-suggester backend")
        async with httpx.AsyncClient() as client:
            jf, ol = await asyncio.gather(
                _check_service(client, f"{settings.jellyfin_url}/health", _logger),
                _check_service(client, f"{settings.ollama_host}/api/tags", _logger),
            )
        _logger.info("startup checks: jellyfin=%s ollama=%s", jf, ol)
        if jf == "error":
            _logger.warning("jellyfin not reachable at startup")
        if ol == "error":
            _logger.warning("ollama not reachable at startup")
        yield
        _logger.info("shutting down ai-movie-suggester backend")

    application = FastAPI(
        title="ai-movie-suggester",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
    )

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Service health: checks Jellyfin and Ollama connectivity."""
        async with httpx.AsyncClient() as client:
            jf, ol = await asyncio.gather(
                _check_service(
                    client, f"{settings.jellyfin_url}/health", _logger
                ),
                _check_service(
                    client, f"{settings.ollama_host}/api/tags", _logger
                ),
            )
        return HealthResponse(
            jellyfin=jf,
            ollama=ol,
            embeddings=EmbeddingsStatus(total=0, pending=0),
        )

    # Middleware registration order matters:
    # Security headers first, then CORS last (runs first on inbound requests)
    # When spec 03 adds CSRF + rate limiter, order becomes:
    # (1) security headers, (2) CSRF, (3) rate limiter, (4) CORS
    application.add_middleware(SecurityHeadersMiddleware, docs_enabled=docs_enabled)

    # CORS — register last so it runs first on inbound requests
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin_str],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )

    return application


# Module-level app for uvicorn: `uvicorn app.main:app`
settings = Settings()  # type: ignore[call-arg]
app = create_app(settings)
