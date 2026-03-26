"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from app.auth.crypto import derive_keys
from app.auth.router import create_auth_router
from app.auth.service import AuthService, cleanup_expired_sessions
from app.auth.session_store import SessionStore
from app.config import Settings
from app.jellyfin.client import JellyfinClient
from app.logging_config import configure_logging
from app.middleware import SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import create_limiter
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

    # Derive crypto keys from session secret
    cookie_key, column_key = derive_keys(settings.session_secret)

    # Create rate limiter (stateless, safe to create early)
    limiter = create_limiter(settings.trusted_proxy_ips)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Startup: log config, check connectivity. Shutdown: clean up."""
        _logger.info("starting ai-movie-suggester backend")

        # Ensure data directory exists for session DB
        db_dir = pathlib.Path(settings.session_db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # Open session store
        store = SessionStore(settings.session_db_path, column_key)
        await store.init()
        app.state.session_store = store
        app.state.cookie_key = cookie_key

        # Create shared HTTP client and Jellyfin client
        http_client = httpx.AsyncClient(timeout=settings.jellyfin_timeout)
        jf_client = JellyfinClient(
            base_url=settings.jellyfin_url,
            http_client=http_client,
        )
        app.state.jellyfin_client = jf_client

        # Wire auth service and router
        auth_service = AuthService(
            session_store=store,
            jellyfin_client=jf_client,
            session_expiry_hours=settings.session_expiry_hours,
            max_sessions_per_user=settings.max_sessions_per_user,
        )
        auth_router = create_auth_router(
            auth_service=auth_service,
            session_store=store,
            settings=settings,
            cookie_key=cookie_key,
            limiter=limiter,
        )
        app.include_router(auth_router)

        # Startup connectivity checks
        async with httpx.AsyncClient() as check_client:
            jf, ol = await asyncio.gather(
                _check_service(
                    check_client,
                    f"{settings.jellyfin_url}/health",
                    _logger,
                ),
                _check_service(
                    check_client,
                    f"{settings.ollama_host}/api/tags",
                    _logger,
                ),
            )
        _logger.info("startup checks: jellyfin=%s ollama=%s", jf, ol)
        if jf == "error":
            _logger.warning("jellyfin not reachable at startup")
        if ol == "error":
            _logger.warning("ollama not reachable at startup")

        # Run expired-session cleanup once at startup
        await cleanup_expired_sessions(store, jf_client)

        # Schedule periodic cleanup
        cleanup_interval = settings.session_expiry_hours * 3600 / 4

        async def _periodic_cleanup() -> None:
            while True:
                await asyncio.sleep(cleanup_interval)
                try:
                    await cleanup_expired_sessions(store, jf_client)
                except Exception:
                    _logger.warning("session cleanup failed", exc_info=True)

        cleanup_task = asyncio.create_task(_periodic_cleanup())

        yield

        # Shutdown
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        _logger.info("shutting down ai-movie-suggester backend")
        await store.close()
        await http_client.aclose()

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
                    client,
                    f"{settings.jellyfin_url}/health",
                    _logger,
                ),
                _check_service(
                    client,
                    f"{settings.ollama_host}/api/tags",
                    _logger,
                ),
            )
        return HealthResponse(
            jellyfin=jf,
            ollama=ol,
            embeddings=EmbeddingsStatus(total=0, pending=0),
        )

    # Middleware registration order matters — FastAPI processes middleware
    # in REVERSE registration order, so CORS (registered last) runs first
    # on inbound requests:
    # (1) security headers, (2) CSRF, (3) rate limiter, (4) CORS
    application.add_middleware(SecurityHeadersMiddleware, docs_enabled=docs_enabled)
    application.add_middleware(CSRFMiddleware)

    # Rate limiter state (slowapi needs it on app.state)
    application.state.limiter = limiter
    application.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,  # type: ignore[arg-type]
    )

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
