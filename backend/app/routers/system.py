"""Health, version and doors, settings, and the live stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import __version__
from ..config import get_settings
from ..deps import CurrentAccount, DbSession
from ..meldungen import fehler
from ..services import bus, settings_service

router = APIRouter(prefix="/api", tags=["system"])

#: A comment line every so often keeps proxies from closing a quiet stream.
KEEPALIVE_SECONDS = 20


@router.get("/health", summary="Is the server up? (no sign-in needed)")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/about", summary="Version and which doors are open")
def about(account: CurrentAccount) -> dict[str, Any]:
    settings = get_settings()
    return {
        "version": __version__,
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


@router.get("/settings", summary="The operator's settings")
def read_settings(account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return settings_service.public(db)


@router.put("/settings", summary="Change settings; unknown keys and out-of-range numbers are refused")
def write_settings(payload: SettingsIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
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
        elif key == "public_url":
            try:
                value = settings_service.normalize_public_url(str(value))
            except ValueError as error:
                raise fehler(
                    "public_url_invalid", "Use an address like https://nexsift.example.com.", 422, field=key
                ) from error
        if key == "password_login" and value is False and not settings_service.get(db, "oidc_issuer"):
            raise fehler(
                "password_needed", "Set up a sign-in provider before turning the password off.", 409, field=key
            )
        clean[key] = value
    settings_service.save(db, clean)
    return settings_service.public(db)


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
