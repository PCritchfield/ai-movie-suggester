"""Integration tests for SqliteVecRepository lifespan wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.vectors.repository import SqliteVecRepository

if TYPE_CHECKING:
    import pathlib

pytestmark = pytest.mark.requires_sqlite_vec


class TestLifespanIntegration:
    """Verify vec_repo is wired into app lifespan."""

    def test_startup_initialises_vec_repo_on_app_state(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Application startup places SqliteVecRepository on app.state."""
        from app.main import create_app
        from tests.conftest import make_test_settings

        settings = make_test_settings(
            library_db_path=str(tmp_path / "library.db"),
            session_db_path=str(tmp_path / "sessions.db"),
        )
        app = create_app(settings)
        with TestClient(app):
            vec_repo = app.state.vec_repo
            assert isinstance(vec_repo, SqliteVecRepository)

    def test_health_endpoint_returns_embeddings_total(
        self, tmp_path: pathlib.Path
    ) -> None:
        """/health returns embeddings.total reflecting actual vector count."""
        from app.main import create_app
        from tests.conftest import make_test_settings

        settings = make_test_settings(
            library_db_path=str(tmp_path / "library.db"),
            session_db_path=str(tmp_path / "sessions.db"),
        )
        app = create_app(settings)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "embeddings" in data
            assert data["embeddings"]["total"] == 0
            assert data["embeddings"]["pending"] == 0

    def test_shutdown_closes_vec_repo_before_session_store(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Shutdown closes vec_repo before session store (reverse init)."""
        from app.auth.session_store import SessionStore
        from app.main import create_app
        from tests.conftest import make_test_settings

        call_order: list[str] = []

        settings = make_test_settings(
            library_db_path=str(tmp_path / "library.db"),
            session_db_path=str(tmp_path / "sessions.db"),
        )
        app = create_app(settings)

        original_vec_close = SqliteVecRepository.close
        original_store_close = SessionStore.close

        async def tracked_vec_close(self: SqliteVecRepository) -> None:
            call_order.append("vec_repo.close")
            await original_vec_close(self)

        async def tracked_store_close(self: SessionStore) -> None:
            call_order.append("store.close")
            await original_store_close(self)

        with (
            patch.object(SqliteVecRepository, "close", tracked_vec_close),
            patch.object(SessionStore, "close", tracked_store_close),
            TestClient(app),
        ):
            pass  # Startup + shutdown happen in context

        assert "vec_repo.close" in call_order
        assert "store.close" in call_order
        assert call_order.index("vec_repo.close") < call_order.index("store.close"), (
            f"Expected vec_repo.close before store.close, got: {call_order}"
        )


class TestStartupFailures:
    """Verify startup fails clearly on vec_repo errors."""

    def test_startup_fails_on_extension_load_failure(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Startup raises RuntimeError when vec0 extension fails to load."""
        from app.main import create_app
        from tests.conftest import make_test_settings

        settings = make_test_settings(
            library_db_path=str(tmp_path / "library.db"),
            session_db_path=str(tmp_path / "sessions.db"),
        )
        app = create_app(settings)

        with (
            patch.object(
                SqliteVecRepository,
                "init",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Failed to load sqlite-vec extension"),
            ),
            pytest.raises(RuntimeError, match="Failed to load sqlite-vec"),
            TestClient(app),
        ):
            pass

    def test_startup_fails_on_dimension_mismatch(self, tmp_path: pathlib.Path) -> None:
        """Startup raises RuntimeError on dimension mismatch."""
        import asyncio

        from app.main import create_app
        from tests.conftest import make_test_settings

        db_path = tmp_path / "library.db"

        # Pre-populate with different dimensions
        async def prepopulate() -> None:
            repo = SqliteVecRepository(
                db_path=str(db_path),
                expected_model="nomic-embed-text",
                expected_dimensions=384,
            )
            await repo.init()
            await repo.close()

        asyncio.run(prepopulate())

        settings = make_test_settings(
            library_db_path=str(db_path),
            session_db_path=str(tmp_path / "sessions.db"),
        )
        app = create_app(settings)

        with (
            pytest.raises(RuntimeError, match="Dimension mismatch"),
            TestClient(app),
        ):
            pass
