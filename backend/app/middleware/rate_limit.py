"""Rate limiting for the login endpoint using slowapi."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request  # noqa: TC002


def create_limiter(trusted_proxy_ips: str = "127.0.0.1") -> Limiter:
    """Create a slowapi Limiter with proxy-aware IP extraction.

    Only trusts X-Forwarded-For when the connecting IP is in the
    trusted proxy list. Otherwise uses the direct client IP.
    """
    trusted = {ip.strip() for ip in trusted_proxy_ips.split(",")}

    def _get_client_ip(request: Request) -> str:
        client_host = request.client.host if request.client else None
        if client_host in trusted:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return get_remote_address(request)

    return Limiter(key_func=_get_client_ip)
