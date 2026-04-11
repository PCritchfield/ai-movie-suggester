"""Pipeline validation fixtures — Ollama pre-flight, embedding, shared DB.

Pipeline tests validate the full RAG pipeline (embed → search → chat)
against real Ollama inference and Jellyfin test fixtures from Spec 22.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr

from app.config import Settings
from app.embedding.worker import EmbeddingWorker
from app.jellyfin.client import JellyfinClient
from app.library.store import LibraryStore
from app.ollama.client import OllamaEmbeddingClient
from app.sync.engine import SyncEngine
from app.vectors.repository import SqliteVecRepository

# Import fixtures from integration conftest — pytest needs module-level names
# to discover fixtures from sibling directories.
from tests.conftest import TEST_SECRET
from tests.integration.conftest import (  # noqa: F401
    TEST_ADMIN_PASS,
)
from tests.integration.conftest import (
    admin_auth_token as admin_auth_token,
)
from tests.integration.conftest import (
    jellyfin as jellyfin,
)
from tests.integration.conftest import (
    populated_library as populated_library,
)
from tests.integration.conftest import (
    test_users as test_users,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from tests.integration.conftest import JellyfinInstance

_logger = logging.getLogger(__name__)

OLLAMA_HOST = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = "llama3.1:8b"
REQUIRED_MODELS = [EMBED_MODEL, CHAT_MODEL]

# Safety cap for embedding loop — prevent infinite loops
_MAX_EMBED_CYCLES = 20


# ---------------------------------------------------------------------------
# Session-scoped autouse: skip entire session if Ollama is unreachable
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session", autouse=True)
async def _check_ollama() -> None:
    """Skip the entire pipeline session if Ollama is not reachable."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{OLLAMA_HOST}/")
            if resp.status_code != 200:
                pytest.skip("Ollama not reachable — run 'ollama serve' first")
        except httpx.TransportError:
            pytest.skip("Ollama not reachable — run 'ollama serve' first")


# ---------------------------------------------------------------------------
# Session-scoped: ensure required models are pulled
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def _ensure_models(_check_ollama: None) -> None:
    """Pull missing models before tests run."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.get(f"{OLLAMA_HOST}/api/tags")
        resp.raise_for_status()
        available = {m["name"] for m in resp.json().get("models", [])}

        for model in REQUIRED_MODELS:
            # Check both exact name and name with :latest suffix
            if model in available or f"{model}:latest" in available:
                _logger.info("Model %s already available", model)
                continue

            _logger.info("Pulling model %s (this may take a while)...", model)
            pull_resp = await client.post(
                f"{OLLAMA_HOST}/api/pull",
                json={"name": model, "stream": False},
                timeout=600.0,
            )
            pull_resp.raise_for_status()
            _logger.info("Model %s pulled successfully", model)


# ---------------------------------------------------------------------------
# Session-scoped: shared database path for all pipeline fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def pipeline_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Shared temp directory for pipeline database files."""
    return tmp_path_factory.mktemp("pipeline")


# ---------------------------------------------------------------------------
# Session-scoped: LibraryStore and SqliteVecRepository sharing one DB
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def pipeline_library_store(
    pipeline_db_path: Path,
) -> AsyncGenerator[LibraryStore, None]:
    """Session-scoped LibraryStore for the pipeline database."""
    db_path = str(pipeline_db_path / "pipeline_library.db")
    store = LibraryStore(db_path)
    await store.init()
    yield store
    await store.close()


@pytest_asyncio.fixture(scope="session")
async def pipeline_vec_repo(
    pipeline_db_path: Path,
) -> AsyncGenerator[SqliteVecRepository, None]:
    """Session-scoped SqliteVecRepository for the pipeline database."""
    db_path = str(pipeline_db_path / "pipeline_library.db")
    repo = SqliteVecRepository(
        db_path=db_path,
        expected_model=EMBED_MODEL,
        expected_dimensions=768,
    )
    await repo.init()
    yield repo
    await repo.close()


# ---------------------------------------------------------------------------
# Shared helper: build Settings for pipeline tests
# ---------------------------------------------------------------------------
def make_pipeline_settings(
    jellyfin_url: str,
    admin_token: str,
    admin_user_id: str,
) -> Settings:
    """Build minimal Settings for pipeline tests.

    Shared between the embedded_library fixture and chat round-trip test
    to avoid divergent Settings construction.
    """
    return Settings(
        jellyfin_url=jellyfin_url,
        session_secret=TEST_SECRET,
        session_secure_cookie=False,
        jellyfin_api_key=SecretStr(admin_token),
        jellyfin_admin_user_id=admin_user_id,
        ollama_host=OLLAMA_HOST,
        log_level="debug",
    )  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Session-scoped: sync + embed all fixtures into the pipeline database
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def embedded_library(
    populated_library: int,  # noqa: ARG001 — forces Jellyfin scan completion
    admin_auth_token: str,
    jellyfin: JellyfinInstance,
    pipeline_library_store: LibraryStore,
    pipeline_vec_repo: SqliteVecRepository,
    _ensure_models: None,
) -> SqliteVecRepository:
    """Sync from Jellyfin and embed all items with real Ollama inference.

    Returns the vec_repo with all fixture items embedded.
    """
    # Build Settings for sync
    async with httpx.AsyncClient(timeout=30.0) as http:
        jf_client = JellyfinClient(base_url=jellyfin.url, http_client=http)
        auth = await jf_client.authenticate(jellyfin.admin_user, TEST_ADMIN_PASS)
        admin_user_id = auth.user_id

    settings = make_pipeline_settings(jellyfin.url, admin_auth_token, admin_user_id)

    # Run sync
    async with httpx.AsyncClient(timeout=30.0) as http:
        jf_client = JellyfinClient(base_url=jellyfin.url, http_client=http)
        engine = SyncEngine(
            library_store=pipeline_library_store,
            jellyfin_client=jf_client,
            settings=settings,
            vector_repository=pipeline_vec_repo,
        )
        result = await engine.run_sync()
        _logger.info(
            "Sync complete: %d created, %d updated, %d failed",
            result.items_created,
            result.items_updated,
            result.items_failed,
        )

    # Embed all items
    async with httpx.AsyncClient(timeout=120.0) as http:
        embed_client = OllamaEmbeddingClient(
            base_url=OLLAMA_HOST,
            http_client=http,
            embed_model=EMBED_MODEL,
        )
        sync_event = asyncio.Event()
        worker = EmbeddingWorker(
            library_store=pipeline_library_store,
            vec_repo=pipeline_vec_repo,
            ollama_client=embed_client,
            settings=settings,
            sync_event=sync_event,
        )

        for cycle in range(_MAX_EMBED_CYCLES):
            pending = await pipeline_library_store.count_pending_embeddings()
            if pending == 0:
                _logger.info("Embedding complete after %d cycles", cycle)
                break
            _logger.info("Embedding cycle %d: %d items pending", cycle + 1, pending)
            await worker.process_cycle()
        else:
            pending = await pipeline_library_store.count_pending_embeddings()
            if pending > 0:
                pytest.fail(
                    f"Embedding did not complete after {_MAX_EMBED_CYCLES} "
                    f"cycles ({pending} items still pending)"
                )

    vec_count = await pipeline_vec_repo.count()
    _logger.info("Pipeline database: %d vectors stored", vec_count)

    return pipeline_vec_repo
