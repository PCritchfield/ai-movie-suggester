# backend/tests/test_jellyfin_client.py
"""Unit tests for the Jellyfin API client (mock httpx)."""

from __future__ import annotations

from app.jellyfin.errors import (
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
)


class TestErrorHierarchy:
    def test_auth_error_is_jellyfin_error(self) -> None:
        assert issubclass(JellyfinAuthError, JellyfinError)

    def test_connection_error_is_jellyfin_error(self) -> None:
        assert issubclass(JellyfinConnectionError, JellyfinError)

    def test_jellyfin_error_is_exception(self) -> None:
        assert issubclass(JellyfinError, Exception)

    def test_auth_error_message(self) -> None:
        err = JellyfinAuthError("Invalid credentials")
        assert str(err) == "Invalid credentials"

    def test_connection_error_message(self) -> None:
        err = JellyfinConnectionError("Connection refused")
        assert str(err) == "Connection refused"
