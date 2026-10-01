"""Push targets: where important things go. The credentials are stored encrypted and never sent back."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import crypto
from ..deps import CurrentAccount, DbSession
from ..meldungen import fehler
from ..models import CRIT, PRIORITIES, Target
from ..services import push, webpush

logger = logging.getLogger("nexsift.targets")

router = APIRouter(prefix="/api/targets", tags=["targets"])

CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
#: Per kind: what is required, and which of the fields are secret (kept when left empty on an edit).
FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "ntfy": {"required": ("url",), "secret": ("token",)},
    "gotify": {"required": ("url", "token"), "secret": ("token",)},
    "telegram": {"required": ("token", "chat_id"), "secret": ("token",)},
    "apprise": {"required": ("url",), "secret": ()},
    "webhook": {"required": ("url",), "secret": ()},
    # The address at the push service and the two keys of the device, from the browser's sign-up.
    # The address counts as secret too: the interface only ever sees its host, so what it sends back is kept.
    "webpush": {"required": ("url", "p256dh", "auth"), "secret": ("url", "p256dh", "auth")},
}


class TargetIn(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(default="", max_length=500)
    token: str = Field(default="", max_length=500)
    chat_id: str = Field(default="", max_length=64)
    #: Web Push only: the device's keys from its sign-up.
    p256dh: str = Field(default="", max_length=200)
    auth: str = Field(default="", max_length=100)
    min_priority: str = CRIT
    quiet_from: str = Field(default="", max_length=5)
    quiet_to: str = Field(default="", max_length=5)
    enabled: bool = True


def _view(target: Target) -> dict[str, Any]:
    config = push.target_config(target)
    url = str(config.get("url", ""))
    device = ""
    if target.kind == "webpush":
        # A device's address at its push service is long and says nothing; its host says which service it is. A
        # short fingerprint of the address lets a browser tell "this is me" without the address leaving the server.
        device = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        url = urlsplit(url).hostname or ""
    return {
        "id": target.id,
        "kind": target.kind,
        "name": target.name,
        "url": url,
        "device": device,
        "chat_id": config.get("chat_id", ""),
        "has_token": bool(config.get("token")),
        "min_priority": target.min_priority,
        "quiet_from": target.quiet_from,
        "quiet_to": target.quiet_to,
        "enabled": target.enabled,
        "last_ok_at": target.last_ok_at.isoformat() if target.last_ok_at else None,
        "last_error": target.last_error,
    }


def _apply(target: Target, payload: TargetIn) -> None:
    if payload.kind not in FIELDS:
        raise fehler("unknown_kind", "Unknown kind of target.", 422)
    if payload.min_priority not in PRIORITIES:
        raise fehler("invalid_priority", "Unknown priority.", 422)
    if bool(payload.quiet_from) != bool(payload.quiet_to) or any(
        value and not CLOCK.match(value) for value in (payload.quiet_from, payload.quiet_to)
    ):
        raise fehler("invalid_quiet_hours", "Quiet hours need a start and an end, like 23:00 and 07:00.", 422)
    config = push.target_config(target) if target.kind == payload.kind else {}
    values = {
        "url": payload.url.strip(),
        "token": payload.token.strip(),
        "chat_id": payload.chat_id.strip(),
        "p256dh": payload.p256dh.strip(),
        "auth": payload.auth.strip(),
    }
    if payload.kind == "webpush" and not values["url"].lower().startswith("https://"):
        # Only a fresh sign-up brings a whole address; the host shown in the list is no address.
        values["url"] = ""
    for key, value in values.items():
        if value or key not in FIELDS[payload.kind]["secret"]:
            config[key] = value
    for key in FIELDS[payload.kind]["required"]:
        if not config.get(key):
            raise fehler("target_field_missing", f"The field {key} is required for this target.", 422, field=key)
    if payload.kind == "webpush" and not webpush.valid_subscription(
        str(config.get("url", "")), str(config.get("p256dh", "")), str(config.get("auth", ""))
    ):
        raise fehler("webpush_invalid", "The browser's sign-up is incomplete. Sign this device up again.", 422)
    if config.get("url") and not str(config["url"]).lower().startswith(("http://", "https://")):
        raise fehler("url_invalid", "The address must start with http:// or https://.", 422, field="url")
    target.kind = payload.kind
    target.name = " ".join(payload.name.split())
    target.config_enc = crypto.encrypt_secret(json.dumps(config))
    target.min_priority = payload.min_priority
    target.quiet_from = payload.quiet_from
    target.quiet_to = payload.quiet_to
    target.enabled = payload.enabled


def _get(db: DbSession, target_id: int) -> Target:
    target = db.get(Target, target_id)
    if target is None:
        raise fehler("not_found", "Target not found.", 404)
    return target


@router.get("", summary="All targets")
def listing(account: CurrentAccount, db: DbSession) -> list[dict[str, Any]]:
    return [_view(row) for row in db.scalars(select(Target).order_by(Target.id))]


@router.post("", status_code=201, summary="New target")
def create(payload: TargetIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    if payload.kind == "webpush":
        # The same browser signing up again (a second tap, or after a reinstall) is the same device: it takes over
        # its old target instead of ringing twice for every message.
        for existing in db.scalars(select(Target).where(Target.kind == "webpush")):
            if push.target_config(existing).get("url") == payload.url.strip():
                _apply(existing, payload)
                db.commit()
                logger.info("Target signed up again id=%s name=%s kind=%s", existing.id, existing.name, existing.kind)
                return _view(existing)
    target = Target(kind=payload.kind, name=payload.name)
    _apply(target, payload)
    db.add(target)
    db.commit()
    # Name and kind only: address, token and keys of a target never go into the log.
    logger.info("Target created id=%s name=%s kind=%s", target.id, target.name, target.kind)
    return _view(target)


@router.put("/{target_id}", summary="Change a target; an empty secret field keeps the stored one")
def update(target_id: int, payload: TargetIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    target = _get(db, target_id)
    _apply(target, payload)
    db.commit()
    logger.info("Target changed id=%s name=%s kind=%s", target.id, target.name, target.kind)
    return _view(target)


@router.post("/{target_id}/test", summary="Send a test push now and say what happened")
async def test(target_id: int, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    target = _get(db, target_id)
    from ..models import utcnow

    try:
        await push.send(target, "nexsift test", "If this reached you, pushes from nexsift arrive here.", CRIT)
    except push.PushError as error:
        target.last_error = str(error)[:300]
        db.commit()
        logger.info("Test push to %s failed: %s", target.name, error)
        return {"ok": False, "error": str(error)}
    target.last_ok_at = utcnow()
    target.last_error = ""
    db.commit()
    return {"ok": True}


@router.delete("/{target_id}", status_code=204, summary="Delete a target")
def delete(target_id: int, account: CurrentAccount, db: DbSession) -> None:
    target = _get(db, target_id)
    name = target.name
    db.delete(target)
    db.commit()
    logger.info("Target deleted id=%s name=%s", target_id, name)


@router.get("/webpush/key", summary="What a browser needs to sign up for Web Push, and whether it is switched on")
def webpush_key(account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    from ..services import settings_service

    return {"enabled": bool(settings_service.get(db, "webpush_enabled")), "key": webpush.public_key(db)}
