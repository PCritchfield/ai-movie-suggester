"""Tests for Play request/response Pydantic models (Spec 24, sub-task 4.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.play.models import PlayRequest, PlayResponse


class TestPlayRequest:
    def test_play_request_shape(self) -> None:
        """PlayRequest round-trips item_id and session_id via model_dump."""
        req = PlayRequest(item_id="item-abc", session_id="sess-xyz")
        assert req.item_id == "item-abc"
        assert req.session_id == "sess-xyz"
        assert req.model_dump() == {"item_id": "item-abc", "session_id": "sess-xyz"}

    def test_play_request_requires_item_id(self) -> None:
        """Missing item_id raises ValidationError."""
        with pytest.raises(ValidationError):
            PlayRequest(session_id="sess-xyz")  # type: ignore[call-arg]

    def test_play_request_requires_session_id(self) -> None:
        """Missing session_id raises ValidationError."""
        with pytest.raises(ValidationError):
            PlayRequest(item_id="item-abc")  # type: ignore[call-arg]


class TestPlayResponse:
    def test_play_response_shape(self) -> None:
        """PlayResponse round-trips status and device_name via model_dump."""
        resp = PlayResponse(status="ok", device_name="Living Room TV")
        assert resp.status == "ok"
        assert resp.device_name == "Living Room TV"
        assert resp.model_dump() == {
            "status": "ok",
            "device_name": "Living Room TV",
        }

    def test_play_response_requires_status(self) -> None:
        with pytest.raises(ValidationError):
            PlayResponse(device_name="TV")  # type: ignore[call-arg]

    def test_play_response_requires_device_name(self) -> None:
        with pytest.raises(ValidationError):
            PlayResponse(status="ok")  # type: ignore[call-arg]
