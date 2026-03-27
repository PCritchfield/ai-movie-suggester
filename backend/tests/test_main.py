"""Unit tests for application lifespan and wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from tests.conftest import make_test_settings


class TestLifespan:
    """Verify LibraryStore wiring in lifespan."""

    @patch("app.main.LibraryStore")
    @patch("app.main.SessionStore")
    def test_library_store_init_called(
        self,
        mock_session_cls: MagicMock,
        mock_library_cls: MagicMock,
    ) -> None:
        """LibraryStore.init() is called during startup."""
        mock_session_instance = AsyncMock()
        mock_session_cls.return_value = mock_session_instance
        mock_library_instance = AsyncMock()
        mock_library_cls.return_value = mock_library_instance

        from app.main import create_app

        settings = make_test_settings()
        app = create_app(settings)

        with TestClient(app):
            mock_library_instance.init.assert_called_once()

    @patch("app.main.LibraryStore")
    @patch("app.main.SessionStore")
    def test_library_store_on_app_state(
        self,
        mock_session_cls: MagicMock,
        mock_library_cls: MagicMock,
    ) -> None:
        """app.state.library_store is set after startup."""
        mock_session_instance = AsyncMock()
        mock_session_cls.return_value = mock_session_instance
        mock_library_instance = AsyncMock()
        mock_library_cls.return_value = mock_library_instance

        from app.main import create_app

        settings = make_test_settings()
        app = create_app(settings)

        with TestClient(app):
            assert app.state.library_store is mock_library_instance

    @patch("app.main.LibraryStore")
    @patch("app.main.SessionStore")
    def test_shutdown_order_library_before_session(
        self,
        mock_session_cls: MagicMock,
        mock_library_cls: MagicMock,
    ) -> None:
        """LibraryStore.close() is called before SessionStore.close()."""
        mock_session_instance = AsyncMock()
        mock_session_cls.return_value = mock_session_instance
        mock_library_instance = AsyncMock()
        mock_library_cls.return_value = mock_library_instance

        # Track call order
        call_order: list[str] = []
        mock_library_instance.close.side_effect = lambda: call_order.append(
            "library_close"
        )
        mock_session_instance.close.side_effect = lambda: call_order.append(
            "session_close"
        )

        from app.main import create_app

        settings = make_test_settings()
        app = create_app(settings)

        with TestClient(app):
            pass  # startup + shutdown

        assert "library_close" in call_order
        assert "session_close" in call_order
        assert call_order.index("library_close") < call_order.index("session_close")

    @patch("app.main.LibraryStore")
    @patch("app.main.SessionStore")
    def test_sync_client_created_with_api_key(
        self,
        mock_session_cls: MagicMock,
        mock_library_cls: MagicMock,
    ) -> None:
        """Sync JellyfinClient created when jellyfin_api_key is set."""
        mock_session_instance = AsyncMock()
        mock_session_cls.return_value = mock_session_instance
        mock_library_instance = AsyncMock()
        mock_library_cls.return_value = mock_library_instance

        from app.main import create_app

        settings = make_test_settings(jellyfin_api_key="test-api-key")
        app = create_app(settings)

        with TestClient(app):
            assert hasattr(app.state, "sync_jellyfin_client")
            assert app.state.sync_jellyfin_client is not None

    @patch("app.main.LibraryStore")
    @patch("app.main.SessionStore")
    def test_no_sync_client_without_api_key(
        self,
        mock_session_cls: MagicMock,
        mock_library_cls: MagicMock,
    ) -> None:
        """Sync JellyfinClient NOT created when jellyfin_api_key is None."""
        mock_session_instance = AsyncMock()
        mock_session_cls.return_value = mock_session_instance
        mock_library_instance = AsyncMock()
        mock_library_cls.return_value = mock_library_instance

        from app.main import create_app

        settings = make_test_settings()
        app = create_app(settings)

        with TestClient(app):
            assert not hasattr(app.state, "sync_jellyfin_client")
