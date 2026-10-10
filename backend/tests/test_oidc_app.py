"""nexsift's own side of sign-in through a provider, beyond the shared contract tests (``tests/nexoidc``):

- the password switch: off only with a linked, active provider; a change of the list that takes the last way in turns
  it back on; the own last link stays while the password is off;
- the way back to nexsift 0.11 (``oidc_store.mirror_legacy``): the old settings and ``accounts.oidc_subject`` always
  describe the entry ``oidc`` or are empty;
- the migration of the old settings, once, and never again after the list was emptied;
- the client secret sealed per provider.
"""

from __future__ import annotations

import getpass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import crypto, reset_password
from app.db import SessionLocal
from app.main import app
from app.models import Account, OidcLink, OidcProvider
from app.security import Brake
from app.services import accounts, oidc_store, settings_service
from app.vendor import nexoidc
from app.vendor.nexoidc import ProviderValues, secret_context
from tests.conftest import PASSWORD, UI
from tests.oidc_helpers import (
    FakeProvider,
    add_provider,
    browser,
    error_in,
    link,
    location,
    sign_in_via_oidc,
)


def _setting(key: str) -> Any:
    with SessionLocal() as db:
        return settings_service.get(db, key)


def _subject() -> str:
    with SessionLocal() as db:
        return db.scalars(select(Account.oidc_subject)).one()


def _linked(client: TestClient, fake: FakeProvider, slug: str = "sso") -> dict[str, Any]:
    entry = add_provider(client, fake, slug=slug)
    back = link(client, fake, PASSWORD, slug=slug)
    assert error_in(back) is None and location(back).startswith("/account?linked=")
    return entry


def _password_off(client: TestClient) -> None:
    answer = client.put("/api/settings", json={"values": {"password_login": False}}, headers=UI)
    assert answer.status_code == 200, answer.text
    assert answer.json()["password_login"] is False


def _password_works() -> bool:
    answer = browser().post("/api/auth/login", json={"name": "admin", "password": PASSWORD})
    return answer.status_code == 200


# --- The password switch -------------------------------------------------------------------------------------------


def test_the_password_stays_on_without_a_linked_active_provider(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    refused = client.put("/api/settings", json={"values": {"password_login": False}}, headers=UI)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "password_needed"
    # A provider alone is not enough: nobody would come in through it.
    add_provider(client, provider)
    refused = client.put("/api/settings", json={"values": {"password_login": False}}, headers=UI)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "password_needed"
    assert _setting("password_login") is True


def test_with_the_password_off_only_the_provider_lets_the_operator_in(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    _linked(client, provider)
    _password_off(client)
    refused = browser().post("/api/auth/login", json={"name": "admin", "password": PASSWORD})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "password_login_off"
    state = browser().get("/api/oidc/state").json()
    assert state == {
        "password_login": False,
        "providers": [{"slug": "sso", "label": "SSO"}],
    }
    visitor = browser()
    assert location(sign_in_via_oidc(visitor, provider)) == "/"
    assert visitor.get("/api/auth/me").json()["name"] == "admin"


@pytest.mark.parametrize("change", ["switched off", "removed", "another issuer"])
def test_a_change_that_takes_the_last_way_in_turns_the_password_back_on(
    client: TestClient, operator: dict, provider: FakeProvider, change: str
) -> None:
    entry = _linked(client, provider)
    _password_off(client)
    assert not _password_works()
    if change == "removed":
        assert client.delete(f"/api/oidc/admin/providers/{entry['id']}", headers=UI).status_code == 200
    else:
        moved = provider.network.add(  # type: ignore[attr-defined]
            FakeProvider(
                "https://moved.example.com", client_id=provider.client_id, client_secret=provider.client_secret
            )
        )
        body = {
            key: entry[key] for key in ("label", "issuer", "client_id", "scopes", "enabled", "trusts_second_factor")
        }
        body.update(client_secret="")
        if change == "switched off":
            body["enabled"] = False
        else:
            body["issuer"] = moved.issuer
        answer = client.put(f"/api/oidc/admin/providers/{entry['id']}", json=body, headers=UI)
        assert answer.status_code == 200, answer.text
    assert _setting("password_login") is True
    assert _password_works()


def test_a_second_way_in_keeps_the_password_off(client: TestClient, operator: dict, provider: FakeProvider) -> None:
    other = provider.network.add(FakeProvider("https://other.example.com"))  # type: ignore[attr-defined]
    first = _linked(client, provider)
    _linked(client, other, slug="other")
    _password_off(client)
    assert client.delete(f"/api/oidc/admin/providers/{first['id']}", headers=UI).status_code == 200
    assert _setting("password_login") is False
    assert not _password_works()


def test_the_last_link_stays_while_the_password_is_off(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = _linked(client, provider)
    _password_off(client)
    refused = client.delete("/api/oidc/sso/link", headers=UI)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "oidc_only_account"
    with SessionLocal() as db:
        account_id = db.scalars(select(Account.id)).one()
    refused = client.request(
        "DELETE", f"/api/oidc/admin/accounts/{account_id}/links/{entry['id']}", json={"password": PASSWORD}, headers=UI
    )
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "oidc_only_account"
    assert client.get("/api/oidc/me").json() == [{"slug": "sso", "label": "SSO", "linked": True}]
    # With the password on again, it can go.
    assert client.put("/api/settings", json={"values": {"password_login": True}}, headers=UI).status_code == 200
    assert client.delete("/api/oidc/sso/link", headers=UI).status_code == 204
    assert client.get("/api/oidc/me").json()[0]["linked"] is False


def test_linking_counts_a_wrong_password_like_a_sign_in(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    add_provider(client, provider)
    wrong = client.post("/api/oidc/sso/link", json={"password": "not-it"}, headers=UI)
    assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "wrong_password"
    with SessionLocal() as db:
        assert db.scalars(select(Account.failed_logins)).one() == 1


def test_the_account_says_whether_it_is_linked(client: TestClient, operator: dict, provider: FakeProvider) -> None:
    assert client.get("/api/auth/me").json()["oidc_linked"] is False
    _linked(client, provider)
    # The address of the account does not matter for the link (it never did since 0.4.0).
    answer = client.put("/api/auth/account", json={"email": "new@example.com"}, headers=UI)
    assert answer.status_code == 200 and answer.json()["oidc_linked"] is True


def test_a_stranger_at_the_provider_is_refused_whatever_address_it_has(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    _linked(client, provider)
    provider.person = {"sub": "stranger", "email": "admin@example.com", "email_verified": True}
    visitor = browser()
    assert error_in(sign_in_via_oidc(visitor, provider)) == "oidc_no_account"
    assert visitor.get("/api/auth/me").status_code == 401


# --- The secret ------------------------------------------------------------------------------------------------------


def test_the_client_secret_is_sealed_for_its_provider_only(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = add_provider(client, provider)
    with SessionLocal() as db:
        sealed = db.get(OidcProvider, entry["id"]).client_secret_enc
    assert provider.client_secret not in sealed
    assert crypto.decrypt_secret(sealed, secret_context(entry["id"])) == provider.client_secret
    assert crypto.decrypt_secret(sealed, secret_context(entry["id"] + 1)) == ""
    assert crypto.decrypt_secret(sealed) == ""
    # Values of before stay readable without a context.
    assert crypto.decrypt_secret(crypto.encrypt_secret("old")) == "old"
    assert "client_secret" not in client.get("/api/oidc/admin/providers").json()[0]


# --- Migration and the way back to 0.11 -------------------------------------------------------------------------------


def _legacy(fake: FakeProvider, *, label: str = "authentik", subject: str = "person-1") -> None:
    with SessionLocal() as db:
        settings_service.save(
            db,
            {
                # 0.11's button wrote the issuer with the slash authentik uses.
                "oidc_issuer": fake.issuer + "/",
                "oidc_client_id": fake.client_id,
                "oidc_client_secret_enc": crypto.encrypt_secret(fake.client_secret),
                "oidc_provider_name": label,
                oidc_store.MIGRATED: False,
            },
        )
        db.scalars(select(Account)).one().oidc_subject = subject
        db.commit()


def _old() -> dict[str, Any]:
    with SessionLocal() as db:
        values = {key: settings_service.get(db, key) for key in oidc_store.LEGACY_KEYS}
        values["oidc_client_secret_enc"] = crypto.decrypt_secret(str(values["oidc_client_secret_enc"] or ""))
        values["subject"] = db.scalars(select(Account.oidc_subject)).one()
        return values


def _migrated(fake: FakeProvider) -> dict[str, Any]:
    _legacy(fake)
    oidc_store.migrate_settings(backup=False)
    with SessionLocal() as db:
        row = db.scalar(select(OidcProvider).where(OidcProvider.slug == "oidc"))
        assert row is not None
        return {"id": row.id, "issuer": row.issuer, "managed": row.managed, "label": row.label}


def test_the_old_provider_becomes_the_entry_oidc_once(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    # As 0.11's authentik button left it: issuer of an authentik application, name "authentik".
    provider = provider.network.add(FakeProvider("https://auth.example.com/application/o/nexsift"))  # type: ignore[attr-defined]
    entry = _migrated(provider)
    assert entry["issuer"] == provider.issuer and entry["managed"] == "authentik" and entry["label"] == "authentik"
    with SessionLocal() as db:
        assert [(row.subject, row.issuer) for row in db.scalars(select(OidcLink))] == [("person-1", provider.issuer)]
    # The old settings still say the same: the way back finds what it knew.
    assert _old() == {
        "oidc_issuer": provider.issuer + "/",
        "oidc_client_id": provider.client_id,
        "oidc_client_secret_enc": provider.client_secret,
        "oidc_provider_name": "authentik",
        "subject": "person-1",
    }
    oidc_store.migrate_settings(backup=False)
    with SessionLocal() as db:
        assert len(db.scalars(select(OidcProvider)).all()) == 1
    # The old callback signs the operator in.
    visitor = browser()
    target = location(visitor.get("/api/oidc/oidc/start"))
    assert target and "redirect_uri=http%3A%2F%2Ftestserver%2Fapi%2Foidc%2Fcallback" in target
    assert location(sign_in_via_oidc(visitor, provider, slug="oidc")) == "/"


def test_a_list_emptied_after_the_migration_does_not_bring_the_old_provider_back(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = _migrated(provider)
    assert client.delete(f"/api/oidc/admin/providers/{entry['id']}", headers=UI).status_code == 200
    assert _old() == {
        "oidc_issuer": "",
        "oidc_client_id": "",
        "oidc_client_secret_enc": "",
        "oidc_provider_name": "",
        "subject": "",
    }
    oidc_store.migrate_settings(backup=False)
    assert client.get("/api/oidc/admin/providers").json() == []


def test_unlinking_and_linking_again_follow_in_the_old_column(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    _migrated(provider)
    assert client.delete("/api/oidc/oidc/link", headers=UI).status_code == 204
    assert _subject() == ""
    provider.person = {"sub": "person-2"}
    back = link(client, provider, PASSWORD, slug="oidc")
    assert error_in(back) is None
    assert _subject() == "person-2"


def test_the_operator_unlinking_empties_the_old_column(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = _migrated(provider)
    with SessionLocal() as db:
        account_id = db.scalars(select(Account.id)).one()
    answer = client.request(
        "DELETE", f"/api/oidc/admin/accounts/{account_id}/links/{entry['id']}", json={"password": PASSWORD}, headers=UI
    )
    assert answer.status_code == 204, answer.text
    assert _subject() == ""


def test_switched_off_the_old_version_finds_no_client(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = _migrated(provider)
    rows = client.get("/api/oidc/admin/providers").json()
    body = {key: rows[0][key] for key in ("label", "issuer", "client_id", "scopes", "enabled", "trusts_second_factor")}
    assert (
        client.put(f"/api/oidc/admin/providers/{entry['id']}", json={**body, "enabled": False}, headers=UI).status_code
        == 200
    )
    old = _old()
    assert old["oidc_client_id"] == "" and old["oidc_client_secret_enc"] == ""
    # The link is kept for when it is on again (only the old version must not use it meanwhile).
    assert old["subject"] == "person-1"
    renamed = {**body, "enabled": True, "label": "Company"}
    assert client.put(f"/api/oidc/admin/providers/{entry['id']}", json=renamed, headers=UI).status_code == 200
    old = _old()
    assert (old["oidc_client_id"], old["oidc_client_secret_enc"]) == (provider.client_id, provider.client_secret)
    assert old["oidc_provider_name"] == "Company"


def test_another_issuer_empties_the_old_settings_for_good(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = _migrated(provider)
    moved = provider.network.add(  # type: ignore[attr-defined]
        FakeProvider("https://moved.example.com", client_id=provider.client_id, client_secret=provider.client_secret)
    )
    rows = client.get("/api/oidc/admin/providers").json()
    body = {key: rows[0][key] for key in ("label", "issuer", "client_id", "scopes", "enabled", "trusts_second_factor")}
    assert (
        client.put(
            f"/api/oidc/admin/providers/{entry['id']}", json={**body, "issuer": moved.issuer}, headers=UI
        ).status_code
        == 200
    )
    assert _old()["oidc_issuer"] == "" and _old()["subject"] == ""
    # Linking at the moved provider does not write into the old column: the old version would take it for the old one.
    moved.person = {"sub": "person-3"}
    assert error_in(link(client, moved, PASSWORD, slug="oidc")) is None
    assert _old() == {
        "oidc_issuer": "",
        "oidc_client_id": "",
        "oidc_client_secret_enc": "",
        "oidc_provider_name": "",
        "subject": "",
    }


def test_the_same_issuer_written_with_a_slash_keeps_everything(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = _migrated(provider)
    rows = client.get("/api/oidc/admin/providers").json()
    body = {key: rows[0][key] for key in ("label", "issuer", "client_id", "scopes", "enabled", "trusts_second_factor")}
    answer = client.put(
        f"/api/oidc/admin/providers/{entry['id']}", json={**body, "issuer": provider.issuer + "/"}, headers=UI
    )
    assert answer.status_code == 200 and answer.json()["dropped"] == 0
    assert _old()["subject"] == "person-1" and _old()["oidc_issuer"] == provider.issuer + "/"


def test_the_operator_unlinks_only_with_the_own_password(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = _linked(client, provider)
    with SessionLocal() as db:
        account_id = db.scalars(select(Account.id)).one()
    path = f"/api/oidc/admin/accounts/{account_id}/links/{entry['id']}"
    refused = client.request("DELETE", path, json={"password": "not-the-password"}, headers=UI)
    assert refused.status_code == 401 and refused.json()["detail"]["code"] == "wrong_password"
    assert client.get("/api/oidc/me").json()[0]["linked"] is True
    assert client.request("DELETE", path, json={"password": PASSWORD}, headers=UI).status_code == 204
    assert client.get("/api/oidc/me").json()[0]["linked"] is False


def test_a_provider_never_makes_accounts_whatever_is_sent(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = add_provider(client, provider, auto_create=True)
    assert entry["auto_create"] is False
    body = {key: entry[key] for key in ("label", "issuer", "client_id", "scopes", "enabled", "trusts_second_factor")}
    saved = client.put(f"/api/oidc/admin/providers/{entry['id']}", json={**body, "auto_create": True}, headers=UI)
    assert saved.json()["auto_create"] is False
    # Not even written straight into the store.
    with SessionLocal() as db:
        store = oidc_store.SqlStore(db)
        made = store.insert_provider(
            ProviderValues(
                slug="direct",
                label="Direct",
                issuer="https://direct.example.com",
                client_id="direct",
                client_secret="",
                scopes="openid",
                enabled=True,
                auto_create=True,
                trusts_second_factor=True,
                managed="",
                position=1,
            )
        )
        store.commit()
        assert made.auto_create is False


# --- The start: what the whole start-up does, not only the function it calls ----------------------------------------


def _restart() -> None:
    """A start of the app: the lifespan runs, the sign-in settings are looked at after the backup."""
    with TestClient(app, base_url="http://testserver"):
        pass


def _entries() -> list[tuple[str, str]]:
    with SessionLocal() as db:
        return [(row.slug, row.issuer) for row in db.scalars(select(OidcProvider))]


def _links() -> list[str]:
    with SessionLocal() as db:
        return sorted(db.scalars(select(OidcLink.subject)))


def test_the_start_moves_the_old_provider_and_takes_over_what_0_11_changed(
    provider: FakeProvider, caplog: pytest.LogCaptureFixture
) -> None:
    with SessionLocal() as db:
        accounts.create_operator(db, "admin", PASSWORD)
    _legacy(provider)
    _restart()
    assert _entries() == [("oidc", provider.issuer)] and _links() == ["person-1"]
    with SessionLocal() as db:
        assert db.scalars(select(OidcProvider.trusts_second_factor)).one() is True
    # A start without a change in 0.11 takes over nothing.
    caplog.clear()
    _restart()
    assert _entries() == [("oidc", provider.issuer)] and _links() == ["person-1"]
    assert "took over" not in caplog.text
    # Back in 0.11 the operator gave the identity up; up again, it stays given up.
    with SessionLocal() as db:
        db.scalars(select(Account)).one().oidc_subject = ""
        db.commit()
    _restart()
    assert _links() == [] and _subject() == ""
    # Back in 0.11 the provider was removed: it stays removed.
    with SessionLocal() as db:
        settings_service.save(db, {key: settings_service.DEFAULTS[key] for key in oidc_store.LEGACY_KEYS})
    _restart()
    assert _entries() == []


def test_the_start_warms_the_tls_context(provider: FakeProvider, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    async def warm() -> None:
        called.append(True)

    monkeypatch.setattr(nexoidc, "warm", warm)
    _restart()
    assert called == [True]


def test_the_fingerprint_follows_every_commit_so_a_start_finds_nothing_changed(
    client: TestClient, operator: dict, provider: FakeProvider
) -> None:
    entry = _migrated(provider)
    stored = _setting(oidc_store.FINGERPRINT)
    assert stored
    with SessionLocal() as db:
        legacy, subjects = oidc_store.read_legacy(db)
        assert oidc_store.migrate.fingerprint(legacy, subjects) == stored
    # A change here (new name, new secret) is the new version's own: the fingerprint moves with it.
    rows = client.get("/api/oidc/admin/providers").json()
    body = {key: rows[0][key] for key in ("label", "issuer", "client_id", "scopes", "enabled", "trusts_second_factor")}
    answer = client.put(
        f"/api/oidc/admin/providers/{entry['id']}",
        json={**body, "label": "Renamed", "client_secret": "another-secret"},
        headers=UI,
    )
    assert answer.status_code == 200, answer.text
    assert _setting(oidc_store.FINGERPRINT) != stored
    with SessionLocal() as db:
        assert oidc_store._changed_by_0_11(db) is False


# --- The refusals and the way back in --------------------------------------------------------------------------------


def test_a_refused_return_counts_against_the_sender(client: TestClient, operator: dict, provider: FakeProvider) -> None:
    add_provider(client, provider)
    # The person is not the operator: refused with oidc_no_account, as often as the brake lets pass for free ...
    seen = [error_in(sign_in_via_oidc(browser(), provider)) for _ in range(Brake.FREE)]
    assert seen == ["oidc_no_account"] * Brake.FREE
    # ... then the sender waits: the next start is refused before it reaches the provider.
    assert error_in(browser().get("/api/oidc/sso/start")) == "too_many_attempts"


def test_the_command_in_the_container_turns_the_password_back_on(
    client: TestClient, operator: dict, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_provider(client, provider)
    assert error_in(link(client, provider, PASSWORD)) is None
    _password_off(client)
    assert _password_works() is False
    new_password = "another-correct-horse-battery"
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": new_password)
    assert reset_password.main() == 0
    assert browser().post("/api/auth/login", json={"name": "admin", "password": new_password}).status_code == 200
    assert browser().get("/api/oidc/state").json()["password_login"] is True
