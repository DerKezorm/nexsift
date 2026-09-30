"""First start, sign-in, sign-out, the own account."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import __version__
from ..config import get_settings
from ..deps import CurrentAccount, DbSession, check_csrf, client_ip
from ..meldungen import fehler, meldung
from ..models import Account
from ..security import MIN_PASSWORD, SESSION_COOKIE, brake, end_all_sessions, end_session, start_session
from ..services import accounts, settings_service
from ..services.accounts import AccountError

logger = logging.getLogger("nexsift.auth")

router = APIRouter(prefix="/api", tags=["auth"])


class SetupIn(BaseModel):
    name: str = Field(max_length=64)
    password: str = Field(max_length=200)
    email: str = Field(default="", max_length=255)


class LoginIn(BaseModel):
    name: str = Field(max_length=64)
    password: str = Field(max_length=200)


class PasswordChangeIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class AccountIn(BaseModel):
    email: str = Field(default="", max_length=255)


class PrefsIn(BaseModel):
    prefs: dict[str, Any]


def secure_cookie(request: Request) -> bool:
    mode = get_settings().cookie_secure.lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    forwarded = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded.split(",")[0].strip() == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=get_settings().session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=secure_cookie(request),
        path="/",
    )


def _raise(error: AccountError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=meldung(error.code, error.message))


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise fehler("password_too_short", f"Use at least {MIN_PASSWORD} characters.", 422, minimum=MIN_PASSWORD)


def account_view(account: Account) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "oidc_linked": bool(account.oidc_subject),
        "prefs": account.prefs or {},
        "created_at": account.created_at.isoformat(),
    }


def sign_in_response(db: DbSession, request: Request, response: Response, account: Account) -> dict[str, Any]:
    token = start_session(db, account, client_ip(request), request.headers.get("user-agent", ""))
    set_session_cookie(response, request, token)
    return account_view(account)


@router.get("/setup", summary="Does nexsift still need its operator account?")
def setup_state(db: DbSession) -> dict[str, Any]:
    return {"needs_setup": accounts.count(db) == 0, "version": __version__, "min_password": MIN_PASSWORD}


@router.post("/setup", summary="Create the operator account (only once)")
def setup(payload: SetupIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    check_csrf(request)
    _check_password(payload.password)
    try:
        account = accounts.create_operator(db, payload.name, payload.password, payload.email)
    except AccountError as error:
        raise _raise(error) from error
    from ..services import presets

    presets.install_defaults(db)
    return sign_in_response(db, request, response, account)


@router.post("/auth/login", summary="Sign in with name and password")
def login(payload: LoginIn, request: Request, response: Response, db: DbSession) -> dict[str, Any]:
    check_csrf(request)
    key = "login:" + client_ip(request)
    wait = brake.wait_seconds(key)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=meldung("too_many_attempts", "Too many attempts. Try again later.", retry_after=wait),
            headers={"Retry-After": str(wait)},
        )
    if not settings_service.get(db, "password_login"):
        raise fehler("password_login_off", "Sign-in with a password is turned off. Use the sign-in provider.", 403)
    try:
        account = accounts.authenticate(db, payload.name, payload.password)
    except AccountError as error:
        brake.failed(key)
        raise _raise(error) from error
    brake.succeeded(key)
    return sign_in_response(db, request, response, account)


@router.post("/auth/logout", status_code=204, summary="Sign out in this browser")
def logout(request: Request, response: Response, db: DbSession) -> None:
    check_csrf(request)
    end_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", summary="The signed-in account")
def me(account: CurrentAccount) -> dict[str, Any]:
    return account_view(account)


@router.put("/auth/password", status_code=204, summary="Change the password")
def change_password(payload: PasswordChangeIn, request: Request, account: CurrentAccount, db: DbSession) -> None:
    _check_password(payload.new)
    if accounts.is_locked(account):
        raise fehler("account_locked", "Too many failed attempts. Try again later.", 429)
    try:
        accounts.change_password(db, account, payload.current, payload.new)
    except AccountError as error:
        raise _raise(error) from error
    end_all_sessions(db, account.id, except_token=request.cookies.get(SESSION_COOKIE))


@router.put("/auth/account", summary="Change the address OIDC sign-in is matched by")
def change_account(payload: AccountIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    try:
        email = accounts.normalize_email(payload.email)
    except AccountError as error:
        raise _raise(error) from error
    if email != account.email:
        # A new address means a new person may sign in through the provider; the old link must not survive it.
        account.oidc_subject = ""
        account.email = email
        db.commit()
    return account_view(account)


@router.put("/me/prefs", summary="Interface preferences")
def save_prefs(payload: PrefsIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    if len(str(payload.prefs)) > 4000:
        raise fehler("prefs_too_large", "The preferences are too large.", 422)
    account.prefs = payload.prefs
    db.commit()
    return account.prefs
