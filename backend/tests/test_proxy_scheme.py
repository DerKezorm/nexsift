"""Behind a proxy that ends TLS, nexsift sees ``http`` while people use ``https``. It believes the proxy's
``X-Forwarded-Proto`` only from the proxies it trusts (``NEXSIFT_TRUSTED_PROXIES``), never from anybody else; out of the
box that list is empty and nobody is trusted, ``127.0.0.1`` included.

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
from app.models import AuthSession
from app.proxy import ForwardedScheme
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
    # The test client is 127.0.0.1, here listed as a proxy (one on the same host in host networking).
    with _running("127.0.0.1", monkeypatch) as base:
        address = _seen(base, PROXY)
    assert str(address["seen"]).startswith("https://127.0.0.1:") and address["proxy_ignored"] is False


def test_out_of_the_box_nobody_is_believed_not_even_127_0_0_1(admin: None, monkeypatch: pytest.MonkeyPatch) -> None:
    with _running("", monkeypatch) as base:
        address = _seen(base, PROXY)
    assert str(address["seen"]).startswith("http://127.0.0.1:")
    assert address["forwarded_proto"] == "https" and address["proxy_ignored"] is True


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


def test_the_rightmost_value_is_the_proxys_the_ones_before_may_be_the_visitors(
    admin: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _running("127.0.0.1", monkeypatch) as base:
        # A visitor sent "http"; the proxy appended what it saw: https.
        assert str(_seen(base, {"X-Forwarded-Proto": "http, https"})["seen"]).startswith("https://")
        # A visitor sent "https" to a proxy that terminates nothing: the proxy appended http.
        assert str(_seen(base, {"X-Forwarded-Proto": "https, http"})["seen"]).startswith("http://")


def test_the_scheme_is_read_without_regard_to_case(admin: None, monkeypatch: pytest.MonkeyPatch) -> None:
    with _running("127.0.0.1", monkeypatch) as base:
        assert str(_seen(base, {"X-Forwarded-Proto": "HTTPS"})["seen"]).startswith("https://")
        assert str(_seen(base, {"X-Forwarded-Proto": "Http, HTTPS"})["seen"]).startswith("https://")
        # Anything else is no scheme: the request stays what it is.
        assert str(_seen(base, {"X-Forwarded-Proto": "ftp"})["seen"]).startswith("http://")


def _cookie(base: str, proto: str) -> str:
    """The session cookie the real server sets for a sign-in that carries this ``X-Forwarded-Proto``."""
    with httpx.Client(base_url=base, headers=UI) as client:
        signed = client.post(
            "/api/auth/login", json={"name": "admin", "password": PASSWORD}, headers={"X-Forwarded-Proto": proto}
        )
        assert signed.status_code == 200, signed.text
        return signed.headers["set-cookie"].lower()


def test_the_session_cookie_is_secure_only_by_a_trusted_proxys_rightmost_scheme(
    admin: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "cookie_secure", "auto")
    with _running("127.0.0.1", monkeypatch) as base:
        assert "secure" in _cookie(base, "HTTPS")
        assert "secure" in _cookie(base, "http, https")
        assert "secure" not in _cookie(base, "https, http")
    # The same header from a sender nobody trusts: the connection is http, so is the cookie.
    for trusted in ("10.99.99.99", ""):
        with _running(trusted, monkeypatch) as base:
            assert "secure" not in _cookie(base, "https")


def _session_ip(base: str, forwarded_for: str) -> str:
    """The sender address the real server stores for a sign-in that carries this ``X-Forwarded-For``."""
    with SessionLocal() as db:
        db.query(AuthSession).delete()
        db.commit()
    with httpx.Client(base_url=base, headers=UI) as client:
        signed = client.post(
            "/api/auth/login", json={"name": "admin", "password": PASSWORD}, headers={"X-Forwarded-For": forwarded_for}
        )
        assert signed.status_code == 200, signed.text
    with SessionLocal() as db:
        return str(db.query(AuthSession).one().ip)


def test_the_sender_address_comes_from_x_forwarded_for_only_behind_a_listed_proxy(
    admin: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _running("", monkeypatch) as base:
        assert _session_ip(base, "203.0.113.7") == "127.0.0.1"
    with _running("127.0.0.1", monkeypatch) as base:
        assert _session_ip(base, "203.0.113.7") == "203.0.113.7"
        # Left of the proxy's own entry is what the sender wrote; the rightmost untrusted hop counts.
        assert _session_ip(base, "198.51.100.1, 203.0.113.7") == "203.0.113.7"


DOORS = ("app.main:app", "app.gateways:gotify", "app.gateways:ntfy")


async def _through_door(door: str, kind: str, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    """Scheme and client a request from 127.0.0.1 with a proxy's headers reaches the app with, through the wrapping
    ``app.serve`` puts around this door."""
    seen: list[tuple[object, object]] = []

    async def probe(scope: dict, receive: object, send: object) -> None:
        seen.append((scope["scheme"], scope["client"][0]))

    monkeypatch.setattr(serve, "import_from_string", lambda name: probe if name == door else None)
    wrapped = serve._server(door, 0, "warning").config.app
    scope = {
        "type": kind,
        "scheme": "ws" if kind == "websocket" else "http",
        "client": ("127.0.0.1", 5000),
        "headers": [(b"x-forwarded-proto", b"https"), (b"x-forwarded-for", b"203.0.113.7")],
    }
    await wrapped(scope, None, None)
    return seen[0]


@pytest.mark.parametrize("door", DOORS)
def test_every_door_believes_nobody_out_of_the_box(door: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxies", "")
    assert asyncio.run(_through_door(door, "http", monkeypatch)) == ("http", "127.0.0.1")
    assert asyncio.run(_through_door(door, "websocket", monkeypatch)) == ("ws", "127.0.0.1")


@pytest.mark.parametrize("door", DOORS)
def test_every_door_believes_a_listed_proxy(door: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxies", "127.0.0.1")
    assert asyncio.run(_through_door(door, "http", monkeypatch)) == ("https", "203.0.113.7")
    assert asyncio.run(_through_door(door, "websocket", monkeypatch)) == ("wss", "203.0.113.7")


def test_uvicorn_and_the_sender_address_read_the_list_alike(monkeypatch: pytest.MonkeyPatch) -> None:
    # A network written with its host bits set, as people do: both places take it as the network.
    monkeypatch.setattr(get_settings(), "trusted_proxies", "127.0.0.5/8, not-an-address")
    assert asyncio.run(_through_door("app.main:app", "http", monkeypatch)) == ("https", "203.0.113.7")
    # Nothing usable in the list is the same as an empty list.
    monkeypatch.setattr(get_settings(), "trusted_proxies", " , not-an-address")
    assert asyncio.run(_through_door("app.main:app", "http", monkeypatch)) == ("http", "127.0.0.1")


def _scope(kind: str, peer: str, *values: bytes) -> dict:
    return {
        "type": kind,
        "scheme": "ws" if kind == "websocket" else "http",
        "client": (peer, 5000),
        "headers": [(b"x-forwarded-proto", value) for value in values],
    }


async def _scheme_after(scope: dict, trusted: str = "127.0.0.1") -> object:
    seen: list[object] = []

    async def inner(scope: dict, receive: object, send: object) -> None:
        seen.append(scope["scheme"])

    await ForwardedScheme(inner, trusted)(scope, None, None)  # type: ignore[arg-type]
    return seen[0]


def test_a_websocket_request_gets_ws_or_wss_by_the_same_rule() -> None:
    assert asyncio.run(_scheme_after(_scope("websocket", "127.0.0.1", b"http, HTTPS"))) == "wss"
    assert asyncio.run(_scheme_after(_scope("websocket", "127.0.0.1", b"https, http"))) == "ws"
    assert asyncio.run(_scheme_after(_scope("http", "127.0.0.1", b"x", b"https"))) == "https"  # the last header line


def test_a_peer_that_is_not_trusted_changes_nothing() -> None:
    assert asyncio.run(_scheme_after(_scope("http", "203.0.113.5", b"https"))) == "http"
    assert asyncio.run(_scheme_after(_scope("websocket", "203.0.113.5", b"https"))) == "ws"
