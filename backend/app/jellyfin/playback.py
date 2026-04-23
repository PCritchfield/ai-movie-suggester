"""Jellyfin playback-dispatch capability client.

Calls ``POST /Sessions/{session_id}/Playing`` on Jellyfin with the caller's
user token. Maps Jellyfin status codes and httpx transport errors to the
Spec-24 exception matrix:

* 204                       -> return ``None`` (success)
* 404, 400                  -> :class:`DeviceOfflineError`
* 401, 403                  -> :class:`PlaybackAuthError`
* 5xx                       -> :class:`PlaybackDispatchError`
* timeout / transport error -> :class:`PlaybackDispatchError`

Exception handlers deliberately do NOT stringify the raw httpx exception,
its ``request.url``, its PEP-678 ``__notes__``, or attach it via ``extra={}``
on log records — all four are potential token/URL leakage channels
(Angua-C2 in the Spec 24 audit).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from app.jellyfin.errors import (
    DeviceOfflineError,
    JellyfinAuthError,
    JellyfinConnectionError,
    JellyfinError,
    PlaybackAuthError,
    PlaybackDispatchError,
)

if TYPE_CHECKING:
    from app.jellyfin.transport import _JellyfinTransport

logger = logging.getLogger(__name__)


class JellyfinPlaybackClient:
    """Dispatches play commands to Jellyfin sessions via an injected transport."""

    def __init__(self, transport: _JellyfinTransport) -> None:
        self._transport = transport

    def __repr__(self) -> str:  # pragma: no cover — smoke only
        # Deliberately omit any auth/token state from the repr.
        return f"<JellyfinPlaybackClient transport={type(self._transport).__name__}>"

    async def dispatch_play(
        self,
        session_id: str,
        item_id: str,
        user_token: str,
    ) -> None:
        """Send a PlayNow command for ``item_id`` to the Jellyfin session.

        Never stores ``user_token``; it flows only as a parameter to the
        transport's ``request`` call.
        """
        path = f"/Sessions/{session_id}/Playing"
        params = {"playCommand": "PlayNow", "itemIds": item_id}
        try:
            await self._transport.request(
                "POST",
                path,
                token=user_token,
                params=params,
                auth_error_message="Jellyfin token rejected during playback dispatch",
            )
        except JellyfinAuthError as exc:
            # Transport already identified this as auth-rejection (401 or
            # the transport's raise_for_status path for 403 below).
            raise PlaybackAuthError(
                "Jellyfin rejected the playback dispatch due to auth"
            ) from exc
        except JellyfinConnectionError as exc:
            # Transport error — no status available. Log type only.
            logger.error(
                "playback dispatch failed: %s",
                type(exc.__cause__).__name__
                if exc.__cause__ is not None
                else type(exc).__name__,
            )
            raise PlaybackDispatchError(
                "Playback dispatch failed due to transport error"
            ) from exc
        except JellyfinError as exc:
            # Non-2xx, non-401 response — inspect the cause's response status.
            cause = exc.__cause__
            status_code = None
            if isinstance(cause, httpx.HTTPStatusError):
                status_code = cause.response.status_code
            if status_code == 403:
                raise PlaybackAuthError(
                    "Jellyfin rejected the playback dispatch due to auth"
                ) from exc
            if status_code in (400, 404):
                raise DeviceOfflineError(
                    "Jellyfin session is no longer available"
                ) from exc
            raise PlaybackDispatchError(
                "Playback dispatch failed — unexpected Jellyfin response"
            ) from exc
