"""Security headers ASGI middleware."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PRODUCTION_CSP = "default-src 'none'; frame-ancestors 'none'"
_DEBUG_CSP = (
    "default-src 'none'; frame-ancestors 'none'; "
    "script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "font-src https://cdn.jsdelivr.net"
)


class SecurityHeadersMiddleware:
    """Adds security headers to every HTTP response.

    Headers:
        X-Content-Type-Options: nosniff
        X-Frame-Options: DENY
        Content-Security-Policy: (strict or debug, computed once at init)
        Cache-Control: no-store (on 2xx responses only)
    """

    def __init__(self, app: ASGIApp, docs_enabled: bool = False) -> None:
        self.app = app
        self.csp_bytes = (_DEBUG_CSP if docs_enabled else _PRODUCTION_CSP).encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 0  # nonlocal sentinel — overwritten in http.response.start

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                headers = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"content-security-policy", self.csp_bytes))
                if 200 <= status_code < 300:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
