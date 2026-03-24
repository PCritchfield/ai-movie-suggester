"""Double-Submit CSRF middleware.

State-changing requests (POST/PUT/PATCH/DELETE) must include an
X-CSRF-Token header matching the csrf_token cookie. The session_id
cookie must also be present. POST /api/auth/login is exempt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request  # noqa: TC002
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from collections.abc import Callable

_EXEMPT_PATHS = {"/api/auth/login"}
_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_CSRF_REJECT = JSONResponse(
    status_code=403,
    content={"detail": "CSRF token missing or invalid"},
)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Validates CSRF token on state-changing requests."""

    async def dispatch(  # type: ignore[override]
        self,
        request: Request,
        call_next: Callable[..., object],
    ) -> Response:
        if (
            request.method in _STATE_CHANGING_METHODS
            and request.url.path not in _EXEMPT_PATHS
        ):
            # Must have a session to make state-changing requests
            if not request.cookies.get("session_id"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing or invalid"},
                )

            header_token = request.headers.get("x-csrf-token")
            cookie_token = request.cookies.get("csrf_token")

            if not header_token or not cookie_token or header_token != cookie_token:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing or invalid"},
                )

        resp: Response = await call_next(request)  # type: ignore[misc]
        return resp
