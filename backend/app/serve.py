"""Start everything: the main app and the Gotify and ntfy doors, each on its port, in one process.

    python -m app.serve

One uvicorn server per port in the same event loop. uvicorn would install its own signal handlers per server
and the last one would win; so they are switched off, and this module ends all servers on Ctrl+C or SIGTERM.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Iterator

import uvicorn

from .config import get_settings


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield

    def install_signal_handlers(self) -> None:  # older uvicorn
        return


def _server(app: str, port: int, log_level: str) -> _Server:
    return _Server(
        uvicorn.Config(
            app,
            host=get_settings().host,
            port=port,
            log_level=log_level,
            proxy_headers=True,
            forwarded_allow_ips=get_settings().trusted_proxies or "127.0.0.1",
            access_log=False,
        )
    )


async def main() -> None:
    settings = get_settings()
    level = settings.log_level.lower()
    servers = [_server("app.main:app", settings.web_port, level)]
    if settings.gotify_port:
        servers.append(_server("app.gateways:gotify", settings.gotify_port, level))
    if settings.ntfy_port:
        servers.append(_server("app.gateways:ntfy", settings.ntfy_port, level))

    def stop() -> None:
        for server in servers:
            server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop)
    try:
        await asyncio.gather(*(server.serve() for server in servers))
    except asyncio.CancelledError:
        stop()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
