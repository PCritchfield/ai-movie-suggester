"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import contextlib
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
from app.library.store import LibraryStore
from app.logging_config import configure_logging
from app.middleware import SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import create_limiter
from app.models import (
    EmbeddingsStatus,
    HealthResponse,
    LibrarySyncStatus,
    ServiceStatus,
)
from app.ollama.client import OllamaEmbeddingClient
from app.sync.engine import SyncEngine
from app.sync.router import router as sync_router
from app.vectors.repository import SqliteVecRepository

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

        # Open library store (after session store)
        lib_db_dir = pathlib.Path(settings.library_db_path).parent
        lib_db_dir.mkdir(parents=True, exist_ok=True)
        library_store = LibraryStore(settings.library_db_path)
        await library_store.init()
        app.state.library_store = library_store

        # Open vector repository (shares library.db, after library store)
        vec_repo = SqliteVecRepository(
            db_path=settings.library_db_path,
            expected_model=settings.ollama_embed_model,
            expected_dimensions=settings.ollama_embed_dimensions,
        )
        try:
            await vec_repo.init()
        except RuntimeError:
            _logger.critical(
                "vec_repo init failed — extension or dimension mismatch",
                exc_info=True,
            )
            raise
        app.state.vec_repo = vec_repo

        # Create shared HTTP client and Jellyfin client
        http_client = httpx.AsyncClient(timeout=settings.jellyfin_timeout)
        jf_client = JellyfinClient(
            base_url=settings.jellyfin_url,
            http_client=http_client,
        )
        app.state.jellyfin_client = jf_client

        # Permission service (stateless in-memory cache, no init()/close())
        from app.permissions.service import PermissionService

        permission_service = PermissionService(
            jellyfin_client=jf_client,
            cache_ttl_seconds=settings.permission_cache_ttl_seconds,
        )
        app.state.permission_service = permission_service

        # Create sync JellyfinClient if API key is configured
        sync_jf_client: JellyfinClient | None = None
        if settings.jellyfin_api_key is not None:
            sync_jf_client = JellyfinClient(
                base_url=settings.jellyfin_url,
                http_client=http_client,
                device_id="ai-movie-suggester-sync",
            )
            app.state.sync_jellyfin_client = sync_jf_client
        else:
            _logger.info("background sync disabled — JELLYFIN_API_KEY not configured")

        # Create SyncEngine (uses sync client if available, else main client)
        sync_engine = SyncEngine(
            library_store=library_store,
            jellyfin_client=sync_jf_client if sync_jf_client else jf_client,
            settings=settings,
            vector_repository=vec_repo,
        )
        app.state.sync_engine = sync_engine

        # Create separate Ollama HTTP client + embedding client
        # Split timeouts: short connect (5s) prevents 120s hang when Ollama
        # is unreachable; long read accommodates slow embedding inference.
        ollama_timeout = httpx.Timeout(
            connect=5.0,
            read=settings.ollama_embed_timeout,
            write=10.0,
            pool=5.0,
        )
        ollama_http = httpx.AsyncClient(timeout=ollama_timeout)
        ollama_client = OllamaEmbeddingClient(
            base_url=settings.ollama_host,
            http_client=ollama_http,
            embed_model=settings.ollama_embed_model,
            health_timeout=settings.ollama_health_timeout,
        )
        app.state.ollama_client = ollama_client

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
            permission_service=permission_service,
        )
        app.include_router(auth_router)

        # Mount sync admin router
        app.include_router(sync_router)

        # Startup connectivity checks
        async with httpx.AsyncClient() as check_client:
            jf_status, ollama_healthy = await asyncio.gather(
                _check_service(
                    check_client,
                    f"{settings.jellyfin_url}/health",
                    _logger,
                ),
                ollama_client.health(),
            )
        ol: ServiceStatus = "ok" if ollama_healthy else "error"
        _logger.info("startup checks: jellyfin=%s ollama=%s", jf_status, ol)
        if jf_status == "error":
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

        # Schedule periodic library sync (if configured)
        sync_task: asyncio.Task[None] | None = None
        if settings.jellyfin_api_key and settings.jellyfin_admin_user_id:

            async def _periodic_sync() -> None:
                while True:
                    await asyncio.sleep(settings.sync_interval_hours * 3600)
                    try:
                        await sync_engine.run_sync()
                    except Exception:
                        _logger.warning("scheduled sync failed", exc_info=True)

            sync_task = asyncio.create_task(_periodic_sync())
            _logger.info(
                "scheduled sync enabled — interval=%.1fh",
                settings.sync_interval_hours,
            )
        else:
            _logger.info(
                "scheduled sync disabled — "
                "JELLYFIN_API_KEY or JELLYFIN_ADMIN_USER_ID not set"
            )

        yield

        # Shutdown (LIFO: sync → cleanup → Ollama → vec → lib → sessions)
        if sync_task is not None:
            sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sync_task
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task
        _logger.info("shutting down ai-movie-suggester backend")
        # Shutdown: reverse init order (vec_repo → library_store → session store)
        await vec_repo.close()
        # TODO(Spec 07): WAL checkpoint after bulk embedding operations
        await library_store.close()
        await store.close()
        await ollama_http.aclose()
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
        async with httpx.AsyncClient() as check_client:
            jf_status, ollama_healthy = await asyncio.gather(
                _check_service(
                    check_client,
                    f"{settings.jellyfin_url}/health",
                    _logger,
                ),
                application.state.ollama_client.health(),
            )
        ol_status: ServiceStatus = "ok" if ollama_healthy else "error"
        # Report real embedding count from vec_repo (if initialised)
        try:
            vec_repo = application.state.vec_repo
            total = await vec_repo.count()
        except Exception:
            total = 0

        # Library sync status (gather DB calls concurrently)
        library_sync: LibrarySyncStatus | None = None
        try:
            lib_store: LibraryStore = application.state.library_store
            last_run, item_count, pending_count = await asyncio.gather(
                lib_store.get_last_sync_run(),
                lib_store.count(),
                lib_store.count_pending_embeddings(),
            )
            library_sync = LibrarySyncStatus(
                last_run_at=last_run.started_at if last_run else None,
                last_run_status=last_run.status if last_run else None,
                items_in_library=item_count,
                items_pending_embedding=pending_count,
            )
        except Exception:
            _logger.debug("library sync status unavailable", exc_info=True)

        return HealthResponse(
            jellyfin=jf_status,
            ollama=ol_status,
            embeddings=EmbeddingsStatus(
                total=total,
                pending=0,  # Updated by embedding pipeline
            ),
            library_sync=library_sync,
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
