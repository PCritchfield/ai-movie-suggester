"""Tests for permission protocol and exception hierarchy."""

from __future__ import annotations

import pytest

from app.permissions.errors import (
    PermissionAuthError,
    PermissionCheckError,
    PermissionError,  # noqa: A004
    PermissionTimeoutError,
)
from app.permissions.models import PermissionServiceProtocol

# --- Protocol structural subtyping ---


class _GoodImpl:
    """Stub that satisfies PermissionServiceProtocol."""

    async def filter_permitted(
        self, user_id: str, token: str, candidate_ids: list[str]
    ) -> list[str]:
        return candidate_ids

    def invalidate_user_cache(self, user_id: str) -> None:
        pass


class _MissingFilter:
    """Stub missing filter_permitted."""

    def invalidate_user_cache(self, user_id: str) -> None:
        pass


class _MissingInvalidate:
    """Stub missing invalidate_user_cache."""

    async def filter_permitted(
        self, user_id: str, token: str, candidate_ids: list[str]
    ) -> list[str]:
        return candidate_ids


class TestProtocol:
    """PermissionServiceProtocol structural subtyping checks."""

    def test_good_impl_satisfies_protocol(self) -> None:
        assert isinstance(_GoodImpl(), PermissionServiceProtocol)

    def test_missing_filter_fails(self) -> None:
        assert not isinstance(_MissingFilter(), PermissionServiceProtocol)

    def test_missing_invalidate_fails(self) -> None:
        assert not isinstance(_MissingInvalidate(), PermissionServiceProtocol)


# --- Exception hierarchy ---


class TestExceptions:
    """All permission exceptions are catchable via the base class."""

    @pytest.mark.parametrize(
        "exc_class",
        [PermissionCheckError, PermissionTimeoutError, PermissionAuthError],
    )
    def test_subclass_caught_by_base(self, exc_class: type[PermissionError]) -> None:
        with pytest.raises(PermissionError):
            raise exc_class("boom")

    @pytest.mark.parametrize(
        "exc_class",
        [PermissionCheckError, PermissionTimeoutError, PermissionAuthError],
    )
    def test_cause_preserved(self, exc_class: type[PermissionError]) -> None:
        cause = ValueError("original")
        try:
            raise exc_class("wrapped") from cause
        except PermissionError as exc:
            assert exc.__cause__ is cause
        else:
            pytest.fail("Exception not raised")

    def test_each_subclass_is_distinct(self) -> None:
        """Each subclass can be caught individually."""
        with pytest.raises(PermissionCheckError):
            raise PermissionCheckError("check")
        with pytest.raises(PermissionTimeoutError):
            raise PermissionTimeoutError("timeout")
        with pytest.raises(PermissionAuthError):
            raise PermissionAuthError("auth")
