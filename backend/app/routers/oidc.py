"""Sign-in through OpenID Connect providers, their list, linking, and the authentik button.

The protocol, who an identity is, the provider list and the button live in the shared module ``vendor/nexoidc``
(the blueprint "Anmeldung mit OIDC und authentik", the same in every nex app); this router puts nexsift around it:
the session, the sign-in brake, the password asked again before linking, and the error answers.

nexsift has one account, the operator (blueprint 06). A provider brings in only the identity the operator linked
while signed in; anybody else the provider knows is refused with ``oidc_no_account``. No invitations, no accounts
made through a provider.

The return leg is a browser redirect, not an API answer: every outcome of a callback ends on a page, ``/`` with the
session cookie, the sign-in page with ``?error=<code>``, or the account settings after linking.

Paths (all below ``/api/oidc``):

| Method | Path | Who |
|---|---|---|
| GET | ``/state`` | anybody: may the password be used, and the active providers (the sign-in page) |
| GET | ``/providers`` | anybody: slug and label of the active entries |
| GET, POST | ``/admin/providers`` | operator: the list (never a secret), add one |
| PUT | ``/admin/providers/order`` | operator: ``{"ids": [...]}`` |
| PUT, DELETE | ``/admin/providers/{id}`` | operator: save (``dropped`` links), remove (``count``, ``only``) |
| GET | ``/admin/providers/{id}/impact?issuer=`` | operator: the numbers for the two confirmations |
| GET | ``/{slug}/start`` | anybody: off to the provider |
| GET | ``/{slug}/callback``, ``/callback`` | anybody: the return (the second belongs to the entry ``oidc``) |
| GET | ``/me`` | signed in: every active entry with ``linked`` |
| POST, DELETE | ``/{slug}/link`` | signed in: link (``{"password"}`` → ``{"url"}``), unlink |
| DELETE | ``/admin/accounts/{account}/links/{provider}`` | operator, with the own password |
| POST | ``/authentik/setup`` | operator: ``{"url", "token", "confirm_issuer_change", "public_url"}`` → always 200 |
| GET, POST | ``/authentik/address`` | operator: what the card shows about the public address; save it ("Use it only") |
| GET | ``/authentik/blueprint`` | operator: ``nexsift-authentik.yaml``; without a public address 409 |
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..db import SessionLocal
from ..deps import CurrentAccount, client_ip
from ..meldungen import fehler
from ..models import Account
from ..security import SESSION_COOKIE, brake, session_account, start_session, verify_password
from ..services import accounts, settings_service
from ..services.oidc_store import SqlStore, way_in
from ..vendor.nexoidc import OidcError, ProviderInvalid, authentik, flow, providers
from ..vendor.nexoidc import accounts as oidc_accounts
from ..vendor.nexoidc.config import current
from .auth import secure_cookie, set_session_cookie

router = APIRouter(prefix="/api/oidc", tags=["oidc"])
logger = logging.getLogger("nexsift.oidc")

#: Codes that cost nothing to produce (a forged return, a braked sender): they do not count against the sender.
FREE_REFUSALS = ("oidc_state_mismatch", "too_many_attempts", "oidc_not_configured")


class ProviderIn(BaseModel):
    label: str = Field(max_length=200)
    slug: str = Field(default="", max_length=100)
    issuer: str = Field(max_length=600)
    client_id: str = Field(max_length=300)
    client_secret: str = Field(default="", max_length=2000)
    scopes: str = Field(default="openid profile email", max_length=500)
    enabled: bool = True
    # One account (blueprint 06): never on, whatever is sent; the store writes it off.
    auto_create: bool = False
    # Taken and ignored: nexsift has no second factor, so a provider is always trusted (``_form``).
    trusts_second_factor: bool = True


class PasswordIn(BaseModel):
    password: str = Field(max_length=200)


class SetupIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1, max_length=2000)
    # The second run after the question "another issuer drops the links" (blueprint 03); off by default.
    confirm_issuer_change: bool = False
    # The address the operator confirmed in the card (the browser's own) while nexsift has none yet (blueprint 03).
    public_url: str = Field(default="", max_length=600)


class AddressIn(BaseModel):
    public_url: str = Field(max_length=600)
    # The operator confirmed the question the address change asked (``oidc.admin.addressChangeConfirm``).
    confirm: bool = False


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=200)


@contextmanager
def store() -> Iterator[SqlStore]:
    with SessionLocal() as db:
        yield SqlStore(db)


def _base(request: Request) -> str:
    return str(request.base_url)


def _redirect(target: flow.Redirect, request: Request) -> RedirectResponse:
    # 303: the browser loads the target with GET whatever way it came.
    response = RedirectResponse(target.location, status_code=303)
    cookie = target.cookie
    secure = cookie.secure or secure_cookie(request)
    if cookie.max_age == 0:
        response.delete_cookie(cookie.name, path=cookie.path, secure=secure, httponly=True, samesite="lax")
    else:
        response.set_cookie(
            cookie.name,
            cookie.value,
            max_age=cookie.max_age,
            path=cookie.path,
            httponly=cookie.http_only,
            samesite="lax",
            secure=secure,
        )
    return response


def _form(payload: ProviderIn) -> providers.Form:
    """The form as the module takes it. One account, no second factor of its own: a provider never makes an account
    and always counts as trusted, whatever the request says. "Not trusted" would empty the old settings, and with the
    password off 0.11 would find no way in (blueprint 06)."""
    return providers.Form(**{**payload.model_dump(), "auto_create": False, "trusts_second_factor": True})


def _form_error(exc: ProviderInvalid) -> Exception:
    return fehler(exc.code, exc.message, 422, field=exc.field)


def _check_password(db: Any, account: Account, password: str, request: Request) -> None:
    """The own password once more, counted like a sign-in: wrong ones lock the account and brake the sender."""
    if accounts.is_locked(account):
        raise fehler("account_locked", "Too many failed sign-ins. Try again later.", 429)
    if not account.password_hash or not verify_password(password, account.password_hash):
        accounts.note_failure(db, account)
        brake.failed(_brake_key(request))
        raise fehler("wrong_password", "The password is wrong.", 401)


# --- What the sign-in page needs ----------------------------------------------------------------------------------


@router.get("/state", summary="Password sign-in allowed, and the active providers (no sign-in needed)")
def state() -> dict[str, Any]:
    with store() as s:
        listed = providers.public_list(s)
        operator = accounts.operator(s.db)
        # Without a provider that brings the operator in, the password always counts (the switch cannot be off).
        allowed = (
            bool(settings_service.get(s.db, "password_login")) or operator is None or not way_in(s.db, operator.id)
        )
        return {
            "password_login": allowed,
            "providers": listed,
        }


@router.get("/providers", summary="The active sign-in providers: slug and label (no sign-in needed)")
def public_providers() -> list[dict[str, str]]:
    with store() as s:
        return providers.public_list(s)


# --- The provider list ---------------------------------------------------------------------------------------------


@router.get("/admin/providers", summary="The provider list (never a secret)")
def admin_providers(_account: CurrentAccount, request: Request) -> list[dict[str, Any]]:
    with store() as s:
        coupled = providers.coupled(s)
        return [
            providers.admin_view(entry, _base(request), len(s.links_of_provider(entry.id)), coupled=coupled)
            for entry in s.list_providers()
        ]


@router.post("/admin/providers", status_code=201, summary="Add a provider; the issuer is checked by discovery")
async def add_provider(payload: ProviderIn, account: CurrentAccount, request: Request) -> dict[str, Any]:
    with store() as s:
        try:
            created = await providers.create(s, _form(payload))
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        logger.info("OIDC provider %s added by=%s", created.slug, account.name)
        return providers.admin_view(created, _base(request), 0)


@router.put("/admin/providers/order", summary="Put the providers in this order (the drag handle)")
def order_providers(payload: OrderIn, _account: CurrentAccount) -> list[dict[str, str]]:
    with store() as s:
        try:
            providers.reorder(s, payload.ids)
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        return providers.public_list(s)


@router.put("/admin/providers/{provider_id}", summary="Save a provider; another issuer drops its links")
async def save_provider(
    provider_id: Annotated[int, Path(ge=1)], payload: ProviderIn, account: CurrentAccount, request: Request
) -> dict[str, Any]:
    with store() as s:
        try:
            form = _form(payload)
            saved, dropped = await providers.update(s, provider_id, form)
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
        logger.info("OIDC provider %s saved by=%s", saved.slug, account.name)
        view = providers.admin_view(saved, _base(request), len(s.links_of_provider(saved.id)))
        return {**view, "dropped": dropped}


@router.get("/admin/providers/{provider_id}/impact", summary="Who loses a link when the issuer changes or it goes")
def provider_impact(
    provider_id: Annotated[int, Path(ge=1)],
    _account: CurrentAccount,
    issuer: Annotated[str, Query(max_length=600)] = "",
) -> dict[str, Any]:
    with store() as s:
        if s.get_provider(provider_id) is None:
            raise fehler("provider_unknown", "No such provider.", 404, field="id")
        removal = providers.removal_impact(s, provider_id)
        change = providers.issuer_change_impact(s, provider_id, issuer) if issuer else 0
        return {"issuer_change": change, **asdict(removal)}


@router.delete("/admin/providers/{provider_id}", summary="Remove a provider with its links")
def remove_provider(provider_id: Annotated[int, Path(ge=1)], account: CurrentAccount) -> dict[str, Any]:
    with store() as s:
        try:
            impact = providers.remove(s, provider_id)
        except ProviderInvalid as exc:
            raise _form_error(exc) from exc
    logger.info("OIDC provider %s removed by=%s", provider_id, account.name)
    return asdict(impact)


# --- Start and return ----------------------------------------------------------------------------------------------


def _brake_key(request: Request) -> str:
    return "oidc:" + client_ip(request)


@router.get("/{slug}/start", summary="Send the browser to the provider (no sign-in needed)")
async def start(slug: Annotated[str, Path(max_length=40)], request: Request) -> RedirectResponse:
    # This is the sign-in button. Failures land on the sign-in page with a code; an invitation is refused by the
    # module (one account, blueprint 06).
    invite = request.query_params.get("invite")
    with store() as s:
        try:
            if brake.wait_seconds(_brake_key(request)):
                raise OidcError("too_many_attempts", "sender is braked")
            target = await flow.begin(s, slug, request_base=_base(request), invite=invite)
        except OidcError as exc:
            return _redirect(flow.refused(exc, None), request)
    return _redirect(target, request)


def _signed_in_id(request: Request) -> int | None:
    # Read in a session of its own: looking the session up may commit (last seen), never inside the store's work.
    with SessionLocal() as db:
        account = session_account(db, request.cookies.get(SESSION_COOKIE))
        return account.id if account is not None else None


async def _returned(slug: str, request: Request) -> RedirectResponse:
    """The return from the provider. The order is the module's: the provider's own error, our cookie and state,
    the single use of the state, then the provider; nothing is written before all that passed."""
    cookie = request.cookies.get(current().cookie_name)
    key = _brake_key(request)
    with store() as s:
        try:
            if brake.wait_seconds(key):
                raise OidcError("too_many_attempts", "sender is braked")
            arrival = await flow.finish(s, slug, cookie=cookie, params=dict(request.query_params))
            if arrival.started.purpose == "link":
                oidc_accounts.link(s, arrival, _signed_in_id(request))
                brake.succeeded(key)
                return _redirect(flow.arrived(arrival, flow.linked_page(slug)), request)
            signed = oidc_accounts.sign_in(s, arrival)
        except OidcError as exc:
            if exc.code not in FREE_REFUSALS:
                brake.failed(key)
            return _redirect(flow.refused(exc, cookie), request)
        brake.succeeded(key)
        row = s.db.get(Account, signed.account_id)
        assert row is not None
        response = _redirect(flow.arrived(arrival), request)
        token = start_session(s.db, row, client_ip(request), request.headers.get("user-agent", ""))
        set_session_cookie(response, request, token)
        return response


@router.get("/callback", summary="The return from the provider of the entry oidc (nexsift 0.11 and older)")
async def legacy_callback(request: Request) -> RedirectResponse:
    return await _returned("oidc", request)


@router.get("/{slug}/callback", summary="The return from the provider (no sign-in needed)")
async def callback(slug: Annotated[str, Path(max_length=40)], request: Request) -> RedirectResponse:
    return await _returned(slug, request)


# --- The own account -----------------------------------------------------------------------------------------------


@router.get("/me", summary="The active providers and whether the own account is linked to each")
def my_providers(account: CurrentAccount) -> list[dict[str, Any]]:
    with store() as s:
        linked = {link.provider_id for link in s.links_of_account(account.id)}
        return [
            {"slug": entry.slug, "label": entry.label, "linked": entry.id in linked}
            for entry in s.list_providers()
            if entry.enabled
        ]


@router.post("/{slug}/link", summary="Start linking the own account to a provider; needs the password")
async def link_start(
    slug: Annotated[str, Path(max_length=40)],
    payload: PasswordIn,
    request: Request,
    response: Response,
    account: CurrentAccount,
) -> dict[str, str]:
    """Linking hands the account to whoever the browser is at the provider, so it asks for the password: a page
    elsewhere cannot start it (the header), and neither can somebody at an unattended browser."""
    with store() as s:
        row = s.db.get(Account, account.id)
        assert row is not None
        # The same brake as before start and return (blueprint 02, "Ablauf" 4): a braked sender links nothing.
        wait = brake.wait_seconds(_brake_key(request))
        if wait:
            raise fehler("too_many_attempts", "Too many attempts. Try again later.", 429, retry_after=wait)
        _check_password(s.db, row, payload.password, request)
        try:
            target = await flow.begin(s, slug, request_base=_base(request), link_account_id=row.id)
        except OidcError as exc:
            raise fehler(exc.code, exc.message, 409) from exc
    cookie = target.cookie
    response.set_cookie(
        cookie.name,
        cookie.value,
        max_age=cookie.max_age,
        path=cookie.path,
        httponly=True,
        samesite="lax",
        secure=cookie.secure or secure_cookie(request),
    )
    logger.info("Linking to provider %s started name=%s", slug, account.name)
    return {"url": target.location}


def _last_way_in(s: SqlStore, account_id: int, provider_id: int) -> bool:
    """With the password sign-in off, is this link the only one that still brings the account in?"""
    return not settings_service.get(s.db, "password_login") and not way_in(s.db, account_id, besides=provider_id)


@router.delete("/{slug}/link", status_code=204, summary="Unlink the own account from a provider")
def unlink(slug: Annotated[str, Path(max_length=40)], account: CurrentAccount) -> None:
    with store() as s:
        entry = s.provider_by_slug(slug)
        if entry is None:
            raise fehler("oidc_not_configured", "This provider is not set up.", 404)
        if _last_way_in(s, account.id, entry.id):
            # The password sign-in is off: without this link nobody could come in.
            raise fehler("oidc_only_account", "This account signs in through this provider only.", 409)
        try:
            oidc_accounts.unlink(s, account.id, entry.id)
        except OidcError as exc:
            raise fehler(exc.code, exc.message, 409) from exc


@router.delete(
    "/admin/accounts/{account_id}/links/{provider_id}",
    status_code=204,
    summary="Operator: unlink an account from a provider (with the own password)",
)
def operator_unlink(
    account_id: Annotated[int, Path(ge=1)],
    provider_id: Annotated[int, Path(ge=1)],
    payload: PasswordIn,
    request: Request,
    account: CurrentAccount,
) -> None:
    # nexsift has one account, so the operator unlinks itself here; the route is the blueprint's, for every app.
    with store() as s:
        operator = s.db.get(Account, account.id)
        assert operator is not None
        _check_password(s.db, operator, payload.password, request)
        if s.db.get(Account, account_id) is None or s.get_provider(provider_id) is None:
            raise fehler("not_found", "Not found.", 404)
        if _last_way_in(s, account_id, provider_id):
            raise fehler("oidc_only_account", "This account signs in through this provider only.", 409)
        try:
            removed = oidc_accounts.unlink(s, account_id, provider_id)
        except OidcError as exc:
            raise fehler(exc.code, exc.message, 409) from exc
        if not removed:
            raise fehler("not_found", "Not found.", 404)
    logger.warning("Operator unlinked account %s from provider %s by=%s", account_id, provider_id, account.name)


# --- authentik ------------------------------------------------------------------------------------------------------


@router.post("/authentik/setup", summary="Set up provider and application in authentik with a one-time token")
async def authentik_setup(payload: SetupIn, account: CurrentAccount, request: Request) -> dict[str, Any]:
    # Always 200 with the steps that ran, a failed one included: the page says why in the operator's language.
    logger.info("authentik setup started by=%s", account.name)
    with store() as s:
        result = await authentik.setup(
            s,
            payload.url,
            payload.token,
            _base(request),
            confirm_issuer_change=payload.confirm_issuer_change,
            public_url=payload.public_url,
            headers=request.headers,
        )
    return result.as_dict()


@router.get("/authentik/address", summary="What the authentik card shows about the public address")
def authentik_address(_account: CurrentAccount, request: Request) -> dict[str, Any]:
    with store() as s:
        return authentik.address_view(s, _base(request), request.headers)


@router.post("/authentik/address", summary="Save the public address (the card's Use it only); asks when it changes")
def authentik_save_address(payload: AddressIn, account: CurrentAccount, request: Request) -> dict[str, Any]:
    with store() as s:
        try:
            view = authentik.save_public_url(s, payload.public_url, _base(request), confirm=payload.confirm)
        except ValueError as error:
            raise fehler("public_url_invalid", "Use an address like https://nexsift.example.com.", 422) from error
        except authentik.PublicUrlChange as asked:
            raise fehler(
                "public_url_change", "The public address changes what authentik knows.", 409, **asked.question
            ) from asked
        except authentik.PublicUrlNotKept as error:
            raise fehler("public_url_needed", "The public address could not be saved.", 409) from error
    logger.info("Public address saved by=%s", account.name)
    return view


@router.get("/authentik/blueprint", summary="Download a blueprint that creates the same objects in authentik")
def authentik_blueprint(_account: CurrentAccount, request: Request) -> Response:
    with store() as s:
        try:
            redirect = authentik.blueprint_redirect(s, _base(request))
        except authentik.PublicUrlNeeded as error:
            raise fehler("public_url_needed", "Set the public address first.", 409) from error
        text = authentik.blueprint(redirect)
    return Response(
        content=text,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{authentik.blueprint_filename()}"'},
    )
