"""Who the provider may bring in: only the operator, and only on the provider's word for the address."""

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.routers.oidc import _resolve
from app.services.oidc import Identity


def _identity(subject: str = "sub-1", email: str | None = "admin@example.com", verified: bool = True) -> Identity:
    return Identity(
        issuer="https://auth.example.com/application/o/nexsift/",
        subject=subject,
        email=email,
        email_verified=verified,
        username="admin",
    )


def test_verified_matching_address_links_the_operator(client: TestClient, operator: dict) -> None:
    with SessionLocal() as db:
        account = _resolve(db, _identity())
        assert not isinstance(account, str) and account.oidc_subject == "sub-1"
        # From now on the subject counts, whatever the address says.
        assert not isinstance(_resolve(db, _identity(email="changed@example.com")), str)


def test_unverified_address_is_refused(client: TestClient, operator: dict) -> None:
    with SessionLocal() as db:
        assert _resolve(db, _identity(verified=False)) == "oidc_email_unverified"
        assert _resolve(db, _identity(email=None)) == "oidc_email_unverified"


def test_other_people_at_the_provider_do_not_get_in(client: TestClient, operator: dict) -> None:
    with SessionLocal() as db:
        assert _resolve(db, _identity(email="someone@example.com")) == "oidc_no_account"
        assert not isinstance(_resolve(db, _identity()), str)
        assert _resolve(db, _identity(subject="sub-2")) == "oidc_no_account"
        assert _resolve(db, _identity(subject="  ")) == "oidc_token_invalid"


def test_state_tells_the_login_page_what_to_show(client: TestClient) -> None:
    assert client.get("/api/oidc/state").json() == {
        "enabled": False,
        "provider_name": "OpenID Connect",
        "password_login": True,
    }
