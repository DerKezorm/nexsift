"""nexoidc contract tests: nexsift's adapter (started from the shared adapter template,
from then on nexsift's own file).

The contract tests in ``tests/nexoidc/`` are the same in every nex app and never edited here. They reach nexsift
only through this class: its real routes, its database and its account. nexsift has one account (one-account variant): the
tests branch on ``single_account`` and refuse invitations and new accounts instead, and ``make_account`` renames the
one account rather than making a second. The test run's data directory and the cleaning between tests come from
``tests/conftest.py``. Passwords are made at run time; none is written into this file.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import httpx
from fastapi.testclient import TestClient
from oidc_contract import StandardAdapter
from sqlalchemy import select

from app import crypto
from app.db import SessionLocal
from app.main import app
from app.models import Account
from app.security import Brake, brake, hash_password
from app.services import accounts, oidc_store, settings_service

OPERATOR_NAME = "operator"
#: The header every changing request of the interface carries.
UI = {"X-Requested-By": "nexsift"}


class Adapter(StandardAdapter):
    package = "app.vendor.nexoidc"
    api = "/api"
    single_account = True
    # No invitations at all: the contract skips their tests and runs 18 and 12 through auto_create (since 1.0.12).
    has_invitations = False
    only_authentik = False
    # One account: nothing to couple, the list stays uncoupled.
    supports_coupling = False
    has_second_factor = False
    # 0.11 asked no code after the provider: the migrated entry trusts it (one-account variant).
    trusted_before = True
    legacy_model = "single"
    old_callback_paths: tuple[str, ...] = ()
    operator_name = OPERATOR_NAME
    # Without a session every route of nexsift answers 401 not_signed_in; there is no member to refuse.
    anonymous_status: tuple[int, ...] = (401,)
    member_status: tuple[int, ...] = (403,)

    def start(self) -> None:
        # tests/conftest.py emptied the database before this test.
        oidc_store.configure()
        self._operator: TestClient | None = None
        self._one = OPERATOR_NAME
        with SessionLocal() as db:
            accounts.create_operator(db, OPERATOR_NAME, self.password_for(OPERATOR_NAME))

    def stop(self) -> None:
        pass

    def browser(self) -> TestClient:
        return TestClient(app, base_url="http://testserver", follow_redirects=False, headers=UI)

    def operator(self) -> TestClient:
        if self._operator is None:
            self._operator = self.browser()
            # The operator is the one account, under whatever name the test gave it.
            self.sign_in_with_password(self._operator, self._one)
        return self._operator

    def make_account(self, name: str, *, password: bool = True, second_factor: bool = False) -> int:
        # One account only: it takes the name and the password the test asks for and stays the operator.
        with SessionLocal() as db:
            row = accounts.operator(db)
            assert row is not None
            row.name = name
            row.password_hash = hash_password(self.password_for(name)) if password else ""
            db.commit()
            self._one = name
            return row.id

    def sign_in_with_password(self, client: Any, name: str) -> None:
        answer = client.post("/api/auth/login", json={"name": name, "password": self.password_for(name)})
        assert answer.status_code == 200, answer.text

    def who(self, client: Any) -> str | None:
        answer = client.get("/api/auth/me")
        return answer.json()["name"] if answer.status_code == 200 else None

    def second_factor_asked(self, client: Any, response: httpx.Response) -> bool:
        # nexsift has no second factor of its own.
        return False

    def account_names(self) -> list[str]:
        with SessionLocal() as db:
            return sorted(db.scalars(select(Account.name)))

    def store(self) -> AbstractContextManager[Any]:
        @contextmanager
        def opened() -> Iterator[oidc_store.SqlStore]:
            with SessionLocal() as db:
                yield oidc_store.SqlStore(db)

        return opened()

    def trip_throttle(self, client: Any) -> None:
        # As many failed runs at the provider from this sender as the brake lets pass (every TestClient is the sender
        # "testclient"): the next start, return and linking wait.
        for _ in range(Brake.FREE + 1):
            brake.failed("oidc:testclient")

    def set_public_url(self, url: str) -> None:
        with SessionLocal() as db:
            settings_service.save(db, {"public_url": url})

    def read_public_url(self) -> str:
        # As a restart would find it: the setting (the environment variable behind it is not set in the tests).
        with SessionLocal() as db:
            return settings_service.public_url(db)

    def save_public_url_route(self, url: str, *, confirm: bool = False) -> httpx.Response:
        # Card 1 and Settings, Addresses save the address through the settings, which ask first (contract test 39).
        return self.operator().put("/api/settings", json={"values": {"public_url": url}, "confirm_public_url": confirm})

    def legacy_setup(
        self, *, issuer: str, client_id: str, client_secret: str, label: str, subjects: dict[str, str]
    ) -> None:
        # As nexsift 0.11 kept its one provider: in the settings, the secret sealed without a context.
        with SessionLocal() as db:
            settings_service.save(
                db,
                {
                    "oidc_issuer": issuer,
                    "oidc_client_id": client_id,
                    "oidc_client_secret_enc": crypto.encrypt_secret(client_secret),
                    "oidc_provider_name": label,
                },
            )
            for name, subject in subjects.items():
                row = db.scalar(select(Account).where(Account.name == name))
                assert row is not None
                row.oidc_subject = subject
            db.commit()

    def run_migration(self) -> None:
        # The whole start: the migration once, then what 0.11 changed since, then the mirror and the fingerprint.
        oidc_store.migrate_settings(backup=False)

    def legacy_read(self) -> dict[str, Any]:
        with SessionLocal() as db:
            legacy, subjects = oidc_store.read_legacy(db)
            names = {row.id: row.name for row in db.scalars(select(Account))}
        return {
            "issuer": legacy.issuer,
            "client_id": legacy.client_id,
            "client_secret": legacy.client_secret,
            "label": legacy.label,
            "auto_create": legacy.auto_create,
            "subjects": {names[account_id]: subject for account_id, subject in subjects},
        }
