"""Health, version and doors, settings, and the live stream."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import __version__
from ..config import get_settings
from ..deps import CurrentAccount, DbSession
from ..meldungen import fehler
from ..services import bus, oidc_store, settings_service, texts, updates
from ..vendor.nexoidc import authentik

logger = logging.getLogger("nexsift.settings")

router = APIRouter(prefix="/api", tags=["system"])

#: A comment line every so often keeps proxies from closing a quiet stream.
KEEPALIVE_SECONDS = 20


@router.get("/health", summary="Is the server up? (no sign-in needed)")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/about", summary="Version, licence, where it comes from, and which doors are open")
def about(account: CurrentAccount) -> dict[str, Any]:
    settings = get_settings()
    return {
        "version": __version__,
        "license": "AGPL-3.0",
        "repo_url": updates.REPO_URL,
        "releases_url": updates.RELEASES_URL,
        "project_url": updates.PROJECT_URL,
        "ports": settings.outside_ports(),
        "doors": {
            "gotify": settings.gotify_port > 0,
            "ntfy": settings.ntfy_port > 0,
            "smtp": settings.smtp_port > 0,
            "syslog": settings.syslog_port > 0,
        },
    }


class SettingsIn(BaseModel):
    values: dict[str, Any]
    #: The operator confirmed the question a changed public address asked (``oidc.admin.addressChangeConfirm``).
    confirm_public_url: bool = False


@router.get("/settings", summary="The operator's settings")
def read_settings(account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return settings_service.public(db)


@router.put("/settings", summary="Change settings; unknown keys and out-of-range numbers are refused")
def write_settings(payload: SettingsIn, account: CurrentAccount, db: DbSession, request: Request) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.values.items():
        if key not in settings_service.PUBLIC_KEYS:
            raise fehler("unknown_setting", f"Unknown setting {key}.", 422, field=key)
        default = settings_service.DEFAULTS[key]
        if key in settings_service.BOUNDS:
            low, high = settings_service.BOUNDS[key]
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise fehler(
                    "out_of_range", f"{key} must be between {low} and {high}.", 422, field=key, low=low, high=high
                )
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise fehler("invalid_input", f"{key} must be true or false.", 422, field=key)
        elif key == "push_mode":
            if value not in settings_service.PUSH_MODES:
                raise fehler("invalid_input", "Unknown push behaviour.", 422, field=key)
        elif key == "push_language":
            if value not in texts.LANGUAGES:
                raise fehler("invalid_input", "Unknown language.", 422, field=key)
        elif key == "backup_schedule":
            if value not in settings_service.BACKUP_SCHEDULES:
                raise fehler("invalid_input", "Unknown backup schedule.", 422, field=key)
        elif key == "public_url":
            try:
                value = settings_service.normalize_public_url(str(value))
            except ValueError as error:
                raise fehler(
                    "public_url_invalid", "Use an address like https://nexsift.example.com.", 422, field=key
                ) from error
        elif key == "sender_host":
            try:
                value = settings_service.normalize_sender_host(str(value))
            except ValueError as error:
                raise fehler(
                    "sender_host_invalid", "Use a host name or an IP address, like 192.168.1.10.", 422, field=key
                ) from error
        if key == "password_login" and value is False and not oidc_store.way_in(db, account.id):
            raise fehler(
                "password_needed",
                "Set up a sign-in provider and link it before turning the password off.",
                409,
                field=key,
            )
        clean[key] = value
    _ask_before_new_public_url(db, clean, request, confirmed=payload.confirm_public_url)
    before = settings_service.public(db)
    settings_service.save(db, clean)
    changed = sorted(key for key, value in clean.items() if before.get(key) != value)
    if changed:
        # Names only: values like the public address are harmless, but a setting added later may not be.
        logger.info("Settings changed keys=%s", ",".join(changed))
    return settings_service.public(db)


def _ask_before_new_public_url(db: Any, clean: dict[str, Any], request: Request, *, confirmed: bool) -> None:
    """A new public address changes the redirect address the sign-in sends. Where authentik still knows the old one
    (the button set it up), or a provider entered by hand does, the operator is asked first: 409 with the question
    and nothing saved (blueprint 03, "Rückleitadresse"); ``confirm_public_url`` says yes. Clearing the address asks
    like any other change: the sign-in then falls back to the address of the request, which authentik may not
    know. The module decides for "" whether there is anything to ask."""
    address = clean.get("public_url")
    if address is None or address == settings_service.get(db, "public_url"):
        return
    try:
        question = authentik.public_url_guard(
            oidc_store.SqlStore(db), str(address), str(request.base_url), confirm=confirmed
        )
    except ValueError as error:
        raise fehler(
            "public_url_invalid", "Use an address like https://nexsift.example.com.", 422, field="public_url"
        ) from error
    if question is not None:
        raise fehler("public_url_change", "The public address changes what authentik knows.", 409, **question)


@router.get("/stream", summary="Live changes as server-sent events")
async def stream(request: Request, account: CurrentAccount) -> StreamingResponse:
    queue = bus.subscribe()

    async def events() -> AsyncIterator[str]:
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {message}\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
