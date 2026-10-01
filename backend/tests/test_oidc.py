"""Who the provider may bring in: only the identity the operator linked while signed in."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import crypto
from app.db import SessionLocal
from app.models import Account
from app.routers.oidc import _resolve
from app.services import oidc, settings_service
from tests.conftest import UI


def _identity(subject: str = "sub-1", email: str | None = "admin@example.com", verified: bool = True) -> oidc.Identity:
    return oidc.Identity(
        issuer="https://auth.example.com/application/o/nexsift/",
        subject=subject,
        email=email,
        email_verified=verified,
        username="admin",
    )


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> dict:
    """A provider that answers every run with the identity in ``who``, without any network."""
    who = {"identity": _identity()}

    async def discovery(issuer: str, *, fresh: bool = False) -> dict:
        return {"authorization_endpoint": "https://auth.example.com/authorize"}

    async def exchange_code(*args, **kwargs) -> tuple[str, str]:
        return "id-token", "access-token"

    async def verify_id_token(*args, **kwargs) -> oidc.Identity:
        return who["identity"]

    monkeypatch.setattr(oidc, "discovery", discovery)
    monkeypatch.setattr(oidc, "exchange_code", exchange_code)
    monkeypatch.setattr(oidc, "verify_id_token", verify_id_token)
    with SessionLocal() as db:
        settings_service.save(
            db,
            {
                "oidc_issuer": "https://auth.example.com/application/o/nexsift/",
                "oidc_client_id": "nexsift",
                "oidc_client_secret_enc": crypto.encrypt_secret("secret"),
            },
        )
    return who


def _back_from_provider(client: TestClient, start: str) -> str:
    """Follows the provider's address back to the callback with the state it carried; returns where nexsift sends
    the browser next."""
    state = parse_qs(urlsplit(start).query)["state"][0]
    response = client.get(f"/api/oidc/callback?code=abc&state={state}", follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


def _linked_subject() -> str:
    with SessionLocal() as db:
        return db.query(Account).one().oidc_subject


def test_an_unlinked_operator_is_not_brought_in_by_a_matching_address(client: TestClient, operator: dict) -> None:
    """The address bridge is gone: authentik vouches for every address, so it proved nothing."""
    with SessionLocal() as db:
        account = db.query(Account).one()
        account.email = "admin@example.com"
        db.commit()
        assert _resolve(db, _identity()) == "oidc_not_linked"


def test_linking_while_signed_in_brings_exactly_that_identity_in(
    client: TestClient, operator: dict, provider: dict
) -> None:
    start = client.post("/api/oidc/link", headers=UI).json()["url"]
    assert _back_from_provider(client, start) == "/settings?tab=signin&linked=1"
    assert _linked_subject() == "sub-1"
    with SessionLocal() as db:
        assert not isinstance(_resolve(db, _identity(email="changed@example.com")), str)
        assert _resolve(db, _identity(subject="sub-2")) == "oidc_no_account"
        assert _resolve(db, _identity(subject="  ")) == "oidc_token_invalid"


def test_a_sign_in_through_the_provider_needs_the_link(client: TestClient, operator: dict, provider: dict) -> None:
    start = client.get("/api/oidc/start", follow_redirects=False).headers["location"]
    assert _back_from_provider(client, start) == "/login?error=oidc_not_linked"
    assert _linked_subject() == ""


def test_a_link_needs_the_session_that_started_it(client: TestClient, operator: dict, provider: dict) -> None:
    start = client.post("/api/oidc/link", headers=UI).json()["url"]
    client.post("/api/auth/logout", headers=UI)
    assert _back_from_provider(client, start) == "/settings?tab=signin&error=oidc_link_session"
    assert _linked_subject() == ""


def test_linking_needs_a_signed_in_operator_and_the_csrf_header(
    client: TestClient, operator: dict, provider: dict
) -> None:
    assert client.post("/api/oidc/link").status_code == 403
    client.post("/api/auth/logout", headers=UI)
    assert client.post("/api/oidc/link", headers=UI).status_code == 401


def test_the_password_stays_until_the_link_exists_and_the_link_stays_while_it_is_the_only_way_in(
    client: TestClient, operator: dict, provider: dict
) -> None:
    off = {"values": {"password_login": False}}
    assert client.put("/api/settings", json=off, headers=UI).json()["detail"]["code"] == "password_needed"
    _back_from_provider(client, client.post("/api/oidc/link", headers=UI).json()["url"])
    assert client.put("/api/settings", json=off, headers=UI).status_code == 200
    assert client.delete("/api/oidc/link", headers=UI).json()["detail"]["code"] == "password_needed"
    client.put("/api/settings", json={"values": {"password_login": True}}, headers=UI)
    assert client.delete("/api/oidc/link", headers=UI).status_code == 204
    assert _linked_subject() == ""


def test_state_tells_the_login_page_what_to_show(client: TestClient) -> None:
    assert client.get("/api/oidc/state").json() == {
        "enabled": False,
        "provider_name": "OpenID Connect",
        "password_login": True,
    }
