"""Unit tests for Device / DeviceType Pydantic models.

The Literal typing on `device_type` must reject any value outside the
four-member set `{"Tv", "Mobile", "Tablet", "Other"}`. Happy-construction
tests cover each of the four literal values.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.jellyfin.device_models import Device


class TestDeviceType:
    def test_device_type_literal_rejects_unknown(self) -> None:
        """Constructing Device with an out-of-set device_type raises."""
        with pytest.raises(ValidationError):
            Device(
                session_id="sess-1",
                name="Living Room",
                client="Jellyfin Android",
                device_type="Phone",  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "device_type",
        ["Tv", "Mobile", "Tablet", "Other"],
    )
    def test_device_type_literal_accepts_each_allowed_value(
        self, device_type: str
    ) -> None:
        """All four literal values construct a valid Device."""
        device = Device(
            session_id="sess-1",
            name="Some Device",
            client="Jellyfin Client",
            device_type=device_type,  # type: ignore[arg-type]
        )
        assert device.device_type == device_type

    def test_device_shape_fields(self) -> None:
        """Device exposes session_id, name, client, device_type."""
        device = Device(
            session_id="sess-42",
            name="Living Room TV",
            client="Jellyfin Android TV",
            device_type="Tv",
        )
        assert device.session_id == "sess-42"
        assert device.name == "Living Room TV"
        assert device.client == "Jellyfin Android TV"
        assert device.device_type == "Tv"

    def test_device_requires_all_fields(self) -> None:
        """Missing any field raises ValidationError."""
        with pytest.raises(ValidationError):
            Device(  # type: ignore[call-arg]
                session_id="sess-1",
                name="dev",
                client="client",
            )
