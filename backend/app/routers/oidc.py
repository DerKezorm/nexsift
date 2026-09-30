"""Sign-in through an OpenID Connect provider, its configuration, and the authentik button.

nexsift has one account. The provider brings it in when its identity has been linked before (the ``subject``),
or when the provider vouches for the operator's address (``email_verified``) and nothing is linked yet; that
first sign-in links it. Anybody else the provider knows is refused: the provider does not decide who owns the
inbox, the operator does, by the address under Settings.

The return leg is a browser redirect: every outcome ends on a page with a code in the address, never in JSON.
The password sign-in stays as the way back in, unless the operator turns it off.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import update

from .. import crypto
from ..deps import CurrentAccount, DbSession, client_ip
from ..meldungen import fehler
from ..models import Account
from ..security import brake, start_session
from ..services import accounts, authentik, oidc, settings_service
from .auth import secure_cookie, set_session_cookie

router = APIRouter(prefix="/api/oidc", tags=["oidc"])
logger = logging.getLogger("nexsift.oidc")

LOGIN_PAGE = "/login"
HOME = "/"
DEFAULT_PROVIDER_NAME = "OpenID Connect"
FOREIGN_TEXT_MAX = 200


class ConfigIn(BaseModel):
    issuer: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=255)
    #: Empty keeps the stored secret; the page never shows it, so an untouched field must not delete it.
    client_secret: str = Field(default="", max_length=500)
    provider_name: str = Field(default="", max_length=64)


class AuthentikSetupIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    token: str = Field(min_length=1, max_length=2000)


@router.get("/config", summary="The OIDC configuration (never the secret)")
def read_config(account: CurrentAccount, request: Request, db: DbSession) -> dict[str, Any]:
    return _config_view(db, request)


@router.put("/config", summary="Set the OIDC provider; the issuer is checked once")
async def write_config(payload: ConfigIn, account: CurrentAccount, request: Request, db: DbSession) -> dict[str, Any]:
    issuer = payload.issuer.strip().rstrip("/")
    if not issuer.lower().startswith(("http://", "https://")):
        raise fehler("issuer_invalid", "The issuer must start with http:// or https://.", 422)
    secret = payload.client_secret.strip()
    stored_secret = str(settings_service.get(db, "oidc_client_secret_enc") or "")
    if not secret and not crypto.decrypt_secret(stored_secret):
        raise fehler("secret_required", "Enter the client secret.", 422)
    try:
        await oidc.discovery(issuer, fresh=True)
    except oidc.OidcError as error:
        code = "issuer_unreachable" if error.code == "oidc_provider_unreachable" else "issuer_invalid"
        raise fehler(code, error.message, 422, reason=error.code) from error
    previous = str(settings_service.get(db, "oidc_issuer") or "")
    if previous and previous != issuer:
        forget_subjects(db, previous, issuer)
    values = {
        "oidc_issuer": issuer,
        "oidc_client_id": payload.client_id.strip(),
        "oidc_provider_name": payload.provider_name.strip(),
    }
    if secret:
        values["oidc_client_secret_enc"] = crypto.encrypt_secret(secret)
    settings_service.save(db, values)
    oidc.clear_cache()
    logger.info("OIDC configured issuer=%s", issuer)
    return _config_view(db, request)


@router.delete("/config", status_code=204, summary="Remove the OIDC configuration")
def delete_config(account: CurrentAccount, db: DbSession) -> None:
    settings_service.save(
        db,
        {
            "oidc_issuer": "",
            "oidc_client_id": "",
            "oidc_client_secret_enc": "",
            "oidc_provider_name": "",
            # Without a provider the password is the only way in; it must not stay switched off.
            "password_login": True,
        },
    )
    oidc.clear_cache()
    logger.info("OIDC configuration removed")


@router.get("/state", summary="Is OIDC sign-in available? (no sign-in needed)")
def state(db: DbSession) -> dict[str, Any]:
    return {
        "enabled": _configured(db),
        "provider_name": _provider_name(db),
        "password_login": bool(settings_service.get(db, "password_login")) or not _configured(db),
    }


def forget_subjects(db: DbSession, previous: str, issuer: str) -> None:
    """A subject only means something together with the provider that issued it."""
    db.execute(update(Account).where(Account.oidc_subject != "").values(oidc_subject=""))
    db.commit()
    logger.warning("OIDC issuer changed from %r to %r, links dropped", previous, issuer)


@router.get("/start", summary="Send the browser to the provider (no sign-in needed)")
async def start(request: Request, db: DbSession) -> RedirectResponse:
    if not _configured(db):
        return _to_login("oidc_not_configured")
    try:
        description = await oidc.discovery(str(settings_service.get(db, "oidc_issuer")))
    except oidc.OidcError as error:
        logger.warning("OIDC sign-in could not be started: %s", error.code)
        return _to_login(error.code)
    attempt = oidc.new_attempt()
    client_id = str(settings_service.get(db, "oidc_client_id"))
    url = oidc.authorization_url(description, client_id, _redirect_uri(db, request), attempt)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        oidc.COOKIE_NAME,
        oidc.pack_attempt(attempt, None),
        max_age=oidc.ATTEMPT_MINUTES * 60,
        path=oidc.COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=secure_cookie(request),
    )
    return response


@router.get("/callback", summary="The return from the provider (no sign-in needed)")
async def callback(
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    attempt = oidc.read_attempt(request.cookies.get(oidc.COOKIE_NAME))

    def refuse(code_out: str, reason: str, *, real: bool = True) -> RedirectResponse:
        (logger.warning if real else logger.debug)("OIDC callback refused (%s): code=%s", reason, code_out)
        return _to_login(code_out)

    if not _configured(db):
        return refuse("oidc_not_configured", "OIDC is not set up", real=False)
    key = "oidc:" + client_ip(request)
    if brake.wait_seconds(key):
        return refuse("too_many_attempts", "sender is braked", real=False)
    if error:
        reason = f"provider returned error={error[:FOREIGN_TEXT_MAX]!r}"
        if error_description:
            reason += f" description={error_description[:FOREIGN_TEXT_MAX]!r}"
        return refuse("oidc_denied", reason, real=False)
    if attempt is None or not code or not state or attempt.get("state") != state:
        return refuse("oidc_state_mismatch", "attempt missing, expired or foreign", real=False)
    if not oidc.consume_state(state):
        return refuse("oidc_state_mismatch", "state was already used", real=False)

    issuer = str(settings_service.get(db, "oidc_issuer"))
    client_id = str(settings_service.get(db, "oidc_client_id"))
    client_secret = crypto.decrypt_secret(str(settings_service.get(db, "oidc_client_secret_enc")))
    try:
        description = await oidc.discovery(issuer)
        id_token, access_token = await oidc.exchange_code(
            description, client_id, client_secret, code, _redirect_uri(db, request), str(attempt.get("verifier", ""))
        )
        identity = await oidc.verify_id_token(
            description, client_id, id_token, str(attempt.get("nonce", "")), access_token
        )
    except oidc.OidcError as failure:
        brake.failed(key)
        return refuse(failure.code, f"the run at the provider failed: {failure.code}")
    brake.succeeded(key)

    account = _resolve(db, identity)
    if isinstance(account, str):
        brake.failed(key)
        return refuse(account, f"no account for this identity: {account} address={oidc.masked(identity.email)}")
    accounts.note_success(db, account)
    response = RedirectResponse(HOME, status_code=303)
    response.delete_cookie(oidc.COOKIE_NAME, path=oidc.COOKIE_PATH)
    token = start_session(db, account, client_ip(request), request.headers.get("user-agent", ""))
    set_session_cookie(response, request, token)
    logger.info("Signed in via OIDC name=%s", account.name)
    return response


@router.post("/authentik/setup", summary="Set up provider and application in authentik with a one-time token")
async def authentik_setup(
    payload: AuthentikSetupIn, account: CurrentAccount, request: Request, db: DbSession
) -> dict[str, Any]:
    url = payload.url.strip().rstrip("/")
    if not url.lower().startswith(("http://", "https://")):
        raise fehler("url_invalid", "The authentik address must start with http:// or https://.", 422)
    logger.info("authentik setup started url=%s", url)
    result = await authentik.setup(db, url, payload.token.strip(), _redirect_uri(db, request))
    return result.as_dict()


@router.get("/authentik/blueprint", summary="Download a blueprint that creates the same objects in authentik")
def authentik_blueprint(account: CurrentAccount, request: Request, db: DbSession) -> Response:
    return Response(
        content=authentik.blueprint(_redirect_uri(db, request)),
        media_type="application/yaml",
        headers={"Content-Disposition": 'attachment; filename="nexsift-authentik.yaml"'},
    )


def _configured(db: DbSession) -> bool:
    return bool(
        settings_service.get(db, "oidc_issuer")
        and settings_service.get(db, "oidc_client_id")
        and settings_service.get(db, "oidc_client_secret_enc")
    )


def _provider_name(db: DbSession) -> str:
    return str(settings_service.get(db, "oidc_provider_name") or "") or DEFAULT_PROVIDER_NAME


def _redirect_uri(db: DbSession, request: Request) -> str:
    base = settings_service.public_url(db) or str(request.base_url).rstrip("/")
    return f"{base}/api/oidc/callback"


def _config_view(db: DbSession, request: Request) -> dict[str, Any]:
    return {
        "configured": _configured(db),
        "issuer": str(settings_service.get(db, "oidc_issuer") or ""),
        "client_id": str(settings_service.get(db, "oidc_client_id") or ""),
        "provider_name": str(settings_service.get(db, "oidc_provider_name") or ""),
        "redirect_uri": _redirect_uri(db, request),
    }


def _to_login(code: str) -> RedirectResponse:
    response = RedirectResponse(f"{LOGIN_PAGE}?error={code}", status_code=303)
    response.delete_cookie(oidc.COOKIE_NAME, path=oidc.COOKIE_PATH)
    return response


def _resolve(db: DbSession, identity: oidc.Identity) -> Account | str:
    """The operator for this identity, or the code of the refusal."""
    if not identity.subject.strip():
        return "oidc_token_invalid"
    account = accounts.operator(db)
    if account is None:
        return "oidc_no_account"
    if account.oidc_subject:
        return account if account.oidc_subject == identity.subject else "oidc_no_account"
    if not identity.email or not identity.email_verified:
        return "oidc_email_unverified"
    if not account.email or identity.email.lower() != account.email.lower():
        return "oidc_no_account"
    account.oidc_subject = identity.subject
    db.commit()
    logger.info("Operator linked to the OIDC identity by verified address")
    return account
