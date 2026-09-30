"""Live updates for the open browsers: a tiny in-process broadcast, read by ``GET /api/stream`` (SSE).

Messages say only *what* changed ("thread 12", "source 3"); the browser fetches the new state itself. So a
lost message costs nothing but a moment of staleness, and the stream never carries content.

Publishing works from any thread: the doors run in FastAPI's thread pool, the SMTP and syslog servers in the
event loop.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

_lock = threading.Lock()
_subscribers: set[asyncio.Queue[str]] = set()
_loop: asyncio.AbstractEventLoop | None = None
#: A browser that stops reading loses messages beyond this, not the server its memory.
QUEUE_MAX = 200


def attach(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue[str]:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_MAX)
    with _lock:
        _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[str]) -> None:
    with _lock:
        _subscribers.discard(queue)


def _deliver(message: str) -> None:
    with _lock:
        queues = list(_subscribers)
    for queue in queues:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            pass


def publish(kind: str, **values: Any) -> None:
    message = json.dumps({"type": kind, **values})
    loop = _loop
    if loop is None or loop.is_closed():
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        _deliver(message)
    else:
        loop.call_soon_threadsafe(_deliver, message)


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)
