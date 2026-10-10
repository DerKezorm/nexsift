"""The scheme a trusted proxy reports.

uvicorn takes ``X-Forwarded-Proto`` only when the whole value is exactly ``http`` or ``https``. A proxy that appends
to a header a visitor sent along ("http, https") or that writes ``HTTPS`` is then not believed, and the sign-in
builds its return address with ``http``. This middleware sits in front of uvicorn's proxy middleware and, for a
trusted peer only, takes the RIGHTMOST value (the one the proxy wrote; everything left of it may come from the
visitor), without regard to case, and only ``http`` or ``https``. For a WebSocket request the same value gives
``ws`` or ``wss``. Everything else (the client address) stays with uvicorn's own middleware.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware, _TrustedHosts

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def forwarded_scheme(headers: list[tuple[bytes, bytes]]) -> str | None:
    """``http`` or ``https`` from the rightmost value of the last ``X-Forwarded-Proto`` header, else None."""
    value: bytes | None = None
    for name, raw in headers:
        if name.lower() == b"x-forwarded-proto":
            value = raw
    if value is None:
        return None
    last = value.decode("latin1").rsplit(",", 1)[-1].strip().lower()
    return last if last in ("http", "https") else None


class ForwardedScheme:
    def __init__(self, app: Any, trusted: str) -> None:
        self.app = app
        self.trusted = _TrustedHosts(trusted)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if client and client[0] in self.trusted:
                scheme = forwarded_scheme(scope["headers"])
                if scheme is not None:
                    scope["scheme"] = scheme.replace("http", "ws") if scope["type"] == "websocket" else scheme
        await self.app(scope, receive, send)


def behind_proxy(app: Any, trusted: str) -> Any:
    """``app`` with the proxy handling of ``trusted`` proxies: this scheme first, then uvicorn's client address."""
    return ForwardedScheme(ProxyHeadersMiddleware(app, trusted_hosts=trusted), trusted)
