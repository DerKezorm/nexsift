"""Behind a proxy that ends TLS, nexsift sees ``http`` while people use ``https``. It believes the proxy's
``X-Forwarded-Proto`` only from the proxies it trusts (``NEXSIFT_TRUSTED_PROXIES``, ``127.0.0.1`` out of the box), never
from anybody else (blueprint 03, "Rückleitadresse"; module 1.0.10, "Hinter einem Proxy").

The test starts the real server of ``app.serve`` on a port of its own, because the scheme is set by uvicorn's proxy
middleware, which a ``TestClient`` does not go through.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest

from app import serve
from app.config import get_settings
from app.db import SessionLocal
from app.services import accounts
from tests.conftest import PASSWORD, UI

PROXY = {"X-Forwarded-Proto": "https"}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _running(trusted: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """nexsift as ``app.serve`` starts it, with the given trusted proxies, on a free port; its address."""
    monkeypatch.setattr(get_settings(), "trusted_proxies", trusted)
    port = _free_port()
    server = serve._server("app.main:app", port, "warning")
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "the server did not start"
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        assert not thread.is_alive()


def _seen(base: str, headers: dict[str, str]) -> dict[str, object]:
    """What the authentik card learns: the address as the server sees this request, and whether it ignored a proxy."""
    with httpx.Client(base_url=base, headers=UI) as client:
        signed = client.post("/api/auth/login", json={"name": "admin", "password": PASSWORD})
        assert signed.status_code == 200, signed.text
        answer = client.get("/api/oidc/authentik/address", headers=headers)
        assert answer.status_code == 200, answer.text
        return dict(answer.json())


@pytest.fixture
def admin() -> None:
    with SessionLocal() as db:
        accounts.create_operator(db, "admin", PASSWORD)


def test_a_trusted_proxy_is_believed_about_the_scheme(admin: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # The test client is 127.0.0.1, which is trusted out of the box.
    with _running("", monkeypatch) as base:
        address = _seen(base, PROXY)
    assert str(address["seen"]).startswith("https://127.0.0.1:") and address["proxy_ignored"] is False


def test_a_sender_that_is_not_trusted_is_not_believed(admin: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Only another address is trusted: the request from 127.0.0.1 carries a header nobody vouches for.
    with _running("10.99.99.99", monkeypatch) as base:
        address = _seen(base, PROXY)
    assert str(address["seen"]).startswith("http://127.0.0.1:")
    assert address["forwarded_proto"] == "https" and address["proxy_ignored"] is True
    # The card then warns, as the module's wording says.


def test_a_trusted_network_is_believed_too(admin: None, monkeypatch: pytest.MonkeyPatch) -> None:
    with _running("127.0.0.0/8, 10.0.0.0/8", monkeypatch) as base:
        address = _seen(base, PROXY)
    assert str(address["seen"]).startswith("https://")
