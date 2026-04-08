"""Tests for the image proxy endpoint."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.crypto import derive_keys
from app.auth.dependencies import get_current_session
from app.auth.models import SessionMeta
from app.config import Settings
from app.images.router import create_images_router
from tests.conftest import TEST_SECRET, make_test_settings

_COOKIE_KEY, _ = derive_keys(TEST_SECRET)

_SESSION_ID = "test-session-id-images"
_USER_ID = "uid-images-1"
_NOW = int(time.time())
_VALID_HEX_ID = "a" * 32  # 32 lowercase hex characters


def _make_session_meta() -> SessionMeta:
    return SessionMeta(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        username="viewer",
        server_name="TestJellyfin",
        expires_at=_NOW + 3600,
    )


def _make_mock_jf_client(http_client: AsyncMock | None = None) -> MagicMock:
    """Create a mock JellyfinClient with a mock _client attribute."""
    jf = MagicMock()
    jf._client = http_client or AsyncMock()
    return jf


def _make_image_app(
    *,
    session_store: AsyncMock | None = None,
    settings: Settings | None = None,
    http_client: AsyncMock | None = None,
) -> tuple[FastAPI, TestClient]:
    settings = settings or make_test_settings()
    app = FastAPI()
    app.state.session_store = session_store or AsyncMock()
    app.state.settings = settings
    app.state.jellyfin_client = _make_mock_jf_client(http_client)

    images_router = create_images_router(settings=settings)
    app.include_router(images_router)

    async def _mock_session() -> SessionMeta:
        return _make_session_meta()

    app.dependency_overrides[get_current_session] = _mock_session

    return app, TestClient(app)


class TestImageProxyValidId:
    def test_valid_id_returns_image_bytes(self) -> None:
        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token"

        mock_http = AsyncMock()
        mock_http.get.return_value = httpx.Response(
            200,
            content=b"\xff\xd8\xff\xe0fake-jpeg-bytes",
            headers={
                "content-type": "image/jpeg",
                "content-length": "18",
            },
        )

        _, client = _make_image_app(session_store=session_store, http_client=mock_http)
        resp = client.get(f"/api/images/{_VALID_HEX_ID}")

        assert resp.status_code == 200
        assert resp.content == b"\xff\xd8\xff\xe0fake-jpeg-bytes"
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.headers["cache-control"] == "private, max-age=86400"
        assert resp.headers["content-length"] == "18"


class TestImageProxyInvalidId:
    def test_non_hex_id_returns_422(self) -> None:
        _, client = _make_image_app()
        resp = client.get("/api/images/not-a-hex-id")
        assert resp.status_code == 422

    def test_uppercase_hex_returns_422(self) -> None:
        _, client = _make_image_app()
        resp = client.get(f"/api/images/{'A' * 32}")
        assert resp.status_code == 422

    def test_short_hex_returns_422(self) -> None:
        _, client = _make_image_app()
        resp = client.get("/api/images/abcdef")
        assert resp.status_code == 422

    def test_path_traversal_returns_422(self) -> None:
        _, client = _make_image_app()
        resp = client.get("/api/images/../../etc/passwd")
        assert resp.status_code in (404, 422)

    def test_id_with_slashes_returns_404_or_422(self) -> None:
        _, client = _make_image_app()
        resp = client.get("/api/images/aabb/ccdd")
        assert resp.status_code in (404, 422)


class TestImageProxyUnauthenticated:
    def test_unauthenticated_returns_401(self) -> None:
        settings = make_test_settings()
        app = FastAPI()
        app.state.session_store = AsyncMock()
        app.state.settings = settings
        app.state.cookie_key = _COOKIE_KEY
        app.state.jellyfin_client = _make_mock_jf_client()

        images_router = create_images_router(settings=settings)
        app.include_router(images_router)
        client = TestClient(app)
        resp = client.get(f"/api/images/{_VALID_HEX_ID}")
        assert resp.status_code == 401


class TestImageProxyJellyfinErrors:
    def test_jellyfin_404_returns_404(self) -> None:
        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token"

        mock_http = AsyncMock()
        mock_http.get.return_value = httpx.Response(404)

        _, client = _make_image_app(session_store=session_store, http_client=mock_http)
        resp = client.get(f"/api/images/{_VALID_HEX_ID}")
        assert resp.status_code == 404

    def test_jellyfin_unreachable_returns_502(self) -> None:
        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token"

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.ConnectError("unreachable")

        _, client = _make_image_app(session_store=session_store, http_client=mock_http)
        resp = client.get(f"/api/images/{_VALID_HEX_ID}")
        assert resp.status_code == 502

    def test_jellyfin_timeout_returns_502(self) -> None:
        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token"

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.TimeoutException("timeout")

        _, client = _make_image_app(session_store=session_store, http_client=mock_http)
        resp = client.get(f"/api/images/{_VALID_HEX_ID}")
        assert resp.status_code == 502


class TestImageProxyHeaderForwarding:
    def test_only_content_type_and_length_forwarded(self) -> None:
        session_store = AsyncMock()
        session_store.get_token.return_value = "jf-token"

        mock_http = AsyncMock()
        mock_http.get.return_value = httpx.Response(
            200,
            content=b"image-data",
            headers={
                "content-type": "image/png",
                "content-length": "10",
                "x-jellyfin-internal": "should-not-appear",
                "server": "Jellyfin",
            },
        )

        _, client = _make_image_app(session_store=session_store, http_client=mock_http)
        resp = client.get(f"/api/images/{_VALID_HEX_ID}")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["content-length"] == "10"
        assert "x-jellyfin-internal" not in resp.headers
