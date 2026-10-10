"""nexsift's side of the shared sign-in module ``vendor/nexoidc``: the ``Store`` over its two tables, the start-up
configuration, the migration from the single provider of the settings, and the two guards around it.

The module (the blueprint "Anmeldung mit OIDC und authentik", the same in every nex app) runs the protocol, decides
who an identity is and keeps the provider list; it never sees a database. What is nexsift's own lives here:

- nexsift has one account, the operator (blueprint 06, "Apps mit nur einem Konto"): no invitations, no accounts made
  through a provider, one identity per provider at most;
- the client secrets are sealed with the server secret under ``oidc-provider:<id>``;
- the address a provider sends stays at the link for display. nexsift's account always has a password and nexsift
  uses the account address for nothing, so it neither follows nor offers it;
- ``mirror_legacy``: the way back to nexsift 0.11, which reads the old settings and ``accounts.oidc_subject``
  (``migrate.way_back`` decides what they show, the stored anchor says which issuer 0.11 knows);
- ``keep_a_way_in``: with the password sign-in off, the operator must keep a linked, active provider, otherwise the
  password comes back on (nexsift did so on removing its provider before the list).

A ``SqlStore`` works inside one SQLAlchemy session, one request. The module commits when an outcome is settled and
rolls back when it refuses after a write. Both guards run before every commit of the store.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import crypto
from ..db import SessionLocal
from ..models import Account, OidcLink, OidcProvider, Setting
from ..vendor import nexoidc
from ..vendor.nexoidc import AccountState, Invite, Link, Provider, ProviderValues, migrate, secret_context
from . import accounts, settings_service

logger = logging.getLogger("nexsift.oidc")

APP_NAME = "nexsift"
#: Where the module sends the browser: the sign-in page with ``?error=``, the account part of the settings after a
#: linking (``/account`` forwards to Settings, Account), the inbox after a sign-in.
LOGIN_PAGE = "/login"
ACCOUNT_PAGE = "/account"
HOME = "/"
#: Longest account name (``accounts.NAME_PATTERN``).
NAME_MAX = 64


def _now() -> datetime:
    return datetime.now(UTC)


def _public_url() -> str:
    with SessionLocal() as db:
        return settings_service.public_url(db)


def _save_public_url(url: str) -> None:
    """The address the operator confirmed in the authentik card, in a transaction of its own and committed at once
    (it outlives a restart, and a run of the button that fails later keeps it). nexsift's own check comes first: it
    takes nothing ``flow.clean_public_url`` refuses, and no path."""
    with SessionLocal() as db:
        put_settings(db, {"public_url": settings_service.normalize_public_url(url)})
        db.commit()


def _server_secret() -> str:
    from ..config import get_settings

    return get_settings().resolved_secret_key()


def configure() -> None:
    """Tell the module who it runs in; once at start-up (and by the tests)."""
    nexoidc.configure(
        nexoidc.AppConfig(
            app_name=APP_NAME,
            server_secret=_server_secret,
            public_url=_public_url,
            save_public_url=_save_public_url,
            single_account=True,
            login_page=LOGIN_PAGE,
            account_page=ACCOUNT_PAGE,
            home=HOME,
        )
    )


class SqlStore:
    """``nexoidc.Store`` over ``oidc_providers`` and ``oidc_links``, inside one session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Providers -------------------------------------------------------------------------------------------------

    def _provider(self, row: OidcProvider | None) -> Provider | None:
        if row is None:
            return None
        return Provider(
            id=row.id,
            slug=row.slug,
            label=row.label,
            issuer=row.issuer,
            client_id=row.client_id,
            client_secret=crypto.decrypt_secret(row.client_secret_enc, secret_context(row.id)),
            scopes=row.scopes,
            enabled=row.enabled,
            auto_create=row.auto_create,
            trusts_second_factor=row.trusts_second_factor,
            managed=row.managed,
            position=row.position,
            redirect_path=row.redirect_path,
            created_at=row.created_at,
            registered_redirect=row.registered_redirect or "",
        )

    def list_providers(self) -> list[Provider]:
        rows = self.db.scalars(select(OidcProvider).order_by(OidcProvider.position, OidcProvider.id))
        return [provider for provider in (self._provider(row) for row in rows) if provider is not None]

    def get_provider(self, provider_id: int) -> Provider | None:
        return self._provider(self.db.get(OidcProvider, provider_id))

    def provider_by_slug(self, slug: str) -> Provider | None:
        return self._provider(self.db.scalar(select(OidcProvider).where(OidcProvider.slug == slug)))

    @staticmethod
    def _apply(row: OidcProvider, values: ProviderValues) -> None:
        row.slug, row.label, row.issuer, row.client_id = values.slug, values.label, values.issuer, values.client_id
        # One account: a provider never makes one, whatever the form says (blueprint 06).
        row.scopes, row.enabled, row.auto_create = values.scopes, values.enabled, False
        row.trusts_second_factor, row.managed, row.position = (
            values.trusts_second_factor,
            values.managed,
            values.position,
        )
        row.redirect_path = values.redirect_path
        if values.registered_redirect is not None:
            row.registered_redirect = values.registered_redirect

    def insert_provider(self, values: ProviderValues) -> Provider:
        row = OidcProvider()
        self._apply(row, values)
        self.db.add(row)
        self.db.flush()
        row.client_secret_enc = crypto.encrypt_secret(values.client_secret or "", secret_context(row.id))
        self.db.flush()
        provider = self._provider(row)
        assert provider is not None
        return provider

    def update_provider(self, provider_id: int, values: ProviderValues) -> Provider:
        row = self.db.get(OidcProvider, provider_id)
        assert row is not None
        self._apply(row, values)
        if values.client_secret is not None:
            row.client_secret_enc = crypto.encrypt_secret(values.client_secret, secret_context(row.id))
        self.db.flush()
        provider = self._provider(row)
        assert provider is not None
        return provider

    def delete_provider(self, provider_id: int) -> None:
        # Foreign keys are on (db.py) and the links would go anyway; said here so nothing hangs on a pragma.
        self.drop_links(provider_id)
        self.db.execute(delete(OidcProvider).where(OidcProvider.id == provider_id))

    # --- Links -----------------------------------------------------------------------------------------------------

    @staticmethod
    def _link(row: OidcLink) -> Link:
        return Link(
            row.provider_id, row.subject, row.account_id, row.issuer, row.email, row.created_at, row.last_used_at
        )

    def find_link(self, provider_id: int, subject: str) -> Link | None:
        row = self.db.scalar(select(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.subject == subject))
        return self._link(row) if row else None

    def links_of_provider(self, provider_id: int) -> list[Link]:
        rows = self.db.scalars(select(OidcLink).where(OidcLink.provider_id == provider_id).order_by(OidcLink.id))
        return [self._link(row) for row in rows]

    def links_of_account(self, account_id: int) -> list[Link]:
        rows = self.db.scalars(select(OidcLink).where(OidcLink.account_id == account_id).order_by(OidcLink.id))
        return [self._link(row) for row in rows]

    def add_link(self, link: Link) -> None:
        self.db.add(
            OidcLink(
                provider_id=link.provider_id,
                subject=link.subject,
                account_id=link.account_id,
                issuer=link.issuer,
                email=link.email,
            )
        )
        self.db.flush()

    def remove_link(self, provider_id: int, account_id: int) -> bool:
        result = self.db.execute(
            delete(OidcLink).where(OidcLink.provider_id == provider_id, OidcLink.account_id == account_id)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def drop_links(self, provider_id: int) -> int:
        result = self.db.execute(delete(OidcLink).where(OidcLink.provider_id == provider_id))
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def touch_link(self, provider_id: int, subject: str, email: str | None) -> None:
        self.db.execute(
            update(OidcLink)
            .where(OidcLink.provider_id == provider_id, OidcLink.subject == subject)
            .values(last_used_at=_now(), email=email)
        )

    # --- Accounts --------------------------------------------------------------------------------------------------

    def account_state(self, account_id: int) -> AccountState | None:
        row = self.db.get(Account, account_id)
        if row is None:
            return None
        # nexsift blocks no account: the lock after wrong passwords keeps out guessing at the password (a stranger
        # can set it off from outside), it does not close the provider's way in. No second factor of its own.
        return AccountState(
            id=row.id, name=row.name, blocked=False, has_password=bool(row.password_hash), has_second_factor=False
        )

    def clean_name(self, raw: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in "._-" else "-" for char in raw.strip().lower())
        cleaned = cleaned.strip("-._")[:NAME_MAX]
        return cleaned if accounts.NAME_PATTERN.match(cleaned) else ""

    def name_taken(self, name: str) -> bool:
        return accounts.by_name(self.db, name) is not None

    def create_account(self, name: str, *, invite: Invite | None, email: str | None) -> int:
        # One account (blueprint 06): the module never asks, ``single_account`` refuses before.
        raise NotImplementedError("nexsift has one account; a provider makes none")

    # --- Invitations (nexsift has none) ------------------------------------------------------------------------------

    def find_invite(self, key: str) -> Invite | None:
        return None

    def consume_invite(self, invite: Invite) -> bool:
        return False

    def accept_invite(self, account_id: int, invite: Invite) -> None:
        raise NotImplementedError("nexsift has no invitations")

    # --- Transaction -----------------------------------------------------------------------------------------------

    def commit(self) -> None:
        # Whatever the module settled: a way in stays, and the version before the list sees the same.
        keep_a_way_in(self.db)
        mirror_legacy(self.db)
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


# --- Who can still come in ---------------------------------------------------------------------------------------


def way_in(db: Session, account_id: int, *, besides: int | None = None) -> bool:
    """Does the account have a link to an active provider (other than ``besides``)? Then the provider brings it in
    while the password sign-in is off."""
    statement = (
        select(func.count())
        .select_from(OidcLink)
        .join(OidcProvider, OidcProvider.id == OidcLink.provider_id)
        .where(OidcLink.account_id == account_id, OidcProvider.enabled.is_(True))
    )
    if besides is not None:
        statement = statement.where(OidcLink.provider_id != besides)
    return bool(db.scalar(statement))


def keep_a_way_in(db: Session) -> None:
    """With the password sign-in off, the operator must have a way in through a provider. A change of the list that
    takes the last one (removed, switched off, another issuer) turns the password sign-in back on, as nexsift did
    on removing its provider before the list. Nothing is committed here."""
    if settings_service.get(db, "password_login"):
        return
    db.flush()
    operator = accounts.operator(db)
    if operator is None or way_in(db, operator.id):
        return
    put_settings(db, {"password_login": True})
    logger.warning("No provider brings the operator in any more: sign-in with a password is on again")


# --- The migration from the single provider of the settings (blueprint 01 "Umstieg", 06 "Wanderung") ------------

#: The settings of the single provider before the list. They stay readable for one version (the way back), then go.
LEGACY_KEYS = ("oidc_issuer", "oidc_client_id", "oidc_client_secret_enc", "oidc_provider_name")
#: Set once the settings were looked at: an operator who later removes every entry must not get the old provider
#: back at the next start.
MIGRATED = "oidc_list_migrated"
#: What the old settings and subjects said after the last mirror (``migrate.fingerprint``), stored in the same
#: transaction. At the next start, ``migrate.resync`` takes over whatever 0.11 changed since.
FINGERPRINT = "oidc_legacy_fingerprint"
#: The issuer 0.11 knows, as it wrote it, or ``migrate.CLOSED`` (``migrate.way_back``). Only the module reads it.
ANCHOR = "oidc_legacy_anchor"
#: How 0.11 behaved after the provider: no code asked (it has no second factor), so the provider is trusted. It
#: stays so: the migration and ``resync`` set it, and the form and the API cannot turn it off (``routers/oidc.py``:
#: "not trusted" with the password off would lock the operator out of 0.11).
TRUSTED_BEFORE = True


def read_legacy(db: Session) -> tuple[migrate.Legacy, list[tuple[int, str]]]:
    """The old settings and the old column, read the one way the migration, the fingerprint and ``resync`` read them
    (the secret unsealed: sealed it differs at every write)."""
    db.flush()
    values = settings_service.get_all(db)
    label = str(values.get("oidc_provider_name") or "")
    legacy = migrate.Legacy(
        issuer=str(values.get("oidc_issuer") or ""),
        client_id=str(values.get("oidc_client_id") or ""),
        client_secret=crypto.decrypt_secret(str(values.get("oidc_client_secret_enc") or "")),
        label=label,
        auto_create=False,
        # The authentik button of nexsift 0.1 to 0.11 named the provider "authentik"; the form never did by itself.
        set_up_by_button=label == "authentik",
    )
    subjects = [
        (account_id, subject)
        for account_id, subject in db.execute(
            select(Account.id, Account.oidc_subject).where(Account.oidc_subject != "").order_by(Account.id)
        )
    ]
    return legacy, subjects


def legacy_plan(db: Session) -> migrate.Plan | None:
    """The entry ``oidc`` and its link the old settings become; None when no provider was set up."""
    legacy, subjects = read_legacy(db)
    return migrate.plan(legacy, subjects, trusts_second_factor=TRUSTED_BEFORE)


def _stored_fingerprint(db: Session) -> str | None:
    return str(settings_service.get(db, FINGERPRINT) or "") or None


def _stored_anchor(db: Session) -> str | None:
    return str(settings_service.get(db, ANCHOR) or "") or None


def migration_due(db: Session) -> bool:
    return (
        not settings_service.get(db, MIGRATED)
        and db.scalar(select(func.count()).select_from(OidcProvider)) == 0
        and legacy_plan(db) is not None
    )


def _changed_by_0_11(db: Session) -> bool:
    """Did 0.11 change the old settings or subjects since the last mirror? (``migrate.changes_since`` reads a
    fingerprint of 1.0.9 in its own form.)"""
    legacy, subjects = read_legacy(db)
    return migrate.changes_since(_stored_fingerprint(db), legacy, subjects).any


def migrate_settings(*, backup: bool = True) -> Provider | None:
    """What every start does with the sign-in settings of 0.11, after a backup (the way back):

    - once, the provider of the settings becomes the entry ``oidc`` with the operator's link (``/api/oidc/callback``
      keeps signing in), after the anchor (the issuer 0.11 knows) is stored; nothing happens when there was no
      provider or the list has entries already;
    - at every later start, whatever 0.11 changed in the old settings and the old column since the last mirror is
      taken over (``migrate.resync``): a link given up there stays given up, a provider removed there stays removed;
    - then, always, also without any provider, the old settings are written back and the fingerprint stored
      (``mirror_legacy``): a provider 0.11 sets up later must be seen at the next start, not thrown away.

    The backup is made only when there is something to take over (``migrate.changes_since``). Returns the entry the
    first migration made, else None."""
    with SessionLocal() as db:
        due = migration_due(db) or (bool(settings_service.get(db, MIGRATED)) and _changed_by_0_11(db))
    if due and backup:
        from . import backups

        backups.create(kind=backups.UPDATE, note="before the sign-in provider list")
    with SessionLocal() as db:
        entry: Provider | None = None
        store = SqlStore(db)

        def keep_anchor(value: str) -> None:
            put_settings(db, {ANCHOR: value})

        if not settings_service.get(db, MIGRATED):
            legacy, _subjects = read_legacy(db)
            keep_anchor(migrate.anchor_of(legacy))
            if migration_due(db):
                entry = migrate.apply(store, legacy_plan(db))
            put_settings(db, {MIGRATED: True})
        else:
            legacy, subjects = read_legacy(db)
            migrate.resync(
                store,
                legacy,
                subjects,
                previous=_stored_fingerprint(db),
                trusts_second_factor=TRUSTED_BEFORE,
                anchor=_stored_anchor(db),
                keep_anchor=keep_anchor,
            )
        # In every case: what the old version will find, and the fingerprint of it (the first one for a database
        # that had none).
        store.commit()
        return entry


def mirror_legacy(db: Session) -> None:
    """The way back to nexsift 0.11 (blueprint 01 "Umstieg" 4): that version reads the old settings ``oidc_*`` and
    ``accounts.oidc_subject``, so they must always show what ``migrate.way_back`` says for the entry ``oidc`` and the
    stored anchor. Otherwise going back would bring a removed provider back, or let a subject in that was given up.
    The rule (the module's README, "Rückweg und wieder hoch"):

    - Entry on and the same issuer as the anchor: the entry in full. Off: issuer and name stay, client empty, the
      old subjects are its links (nexsift trusts every provider, so "not trusted" does not occur).
    - Another issuer, or the entry gone: everything empty for good, the anchor closed.

    The fingerprint of what stands afterwards goes with it, for ``migrate.resync`` at the next start. Nothing is
    committed here; the store calls it before every commit, and so does every other way that changes the account or
    the entry."""
    db.flush()
    store = SqlStore(db)
    entry = store.provider_by_slug(nexoidc.LEGACY_SLUG)
    links = [(link.account_id, link.subject) for link in store.links_of_provider(entry.id)] if entry else []
    mirror = migrate.way_back(entry, links, _stored_anchor(db))
    legacy = mirror.legacy
    changes: dict[str, object] = {
        "oidc_issuer": legacy.issuer,
        "oidc_client_id": legacy.client_id,
        "oidc_provider_name": legacy.label,
        ANCHOR: mirror.anchor,
    }
    # The sealed secret differs at every write; touch it only when the secret itself differs.
    if crypto.decrypt_secret(str(settings_service.get(db, "oidc_client_secret_enc") or "")) != legacy.client_secret:
        changes["oidc_client_secret_enc"] = crypto.encrypt_secret(legacy.client_secret)
    put_settings(db, changes)
    for account in db.scalars(select(Account).where((Account.oidc_subject != "") | Account.id.in_(mirror.subjects))):
        wanted = mirror.subjects.get(account.id, "")
        if account.oidc_subject != wanted:
            account.oidc_subject = wanted
    stored, subjects = read_legacy(db)
    put_settings(db, {FINGERPRINT: migrate.fingerprint(stored, subjects)})


def put_settings(db: Session, changes: dict[str, object]) -> None:
    """Settings written in the open transaction (``settings_service.save`` commits on its own)."""
    for key, value in changes.items():
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
