"""Sources: list, create from a preset, rename, mute, renew the token, send a test message, delete."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..adapters.base import Incoming
from ..deps import CurrentAccount, DbSession
from ..meldungen import fehler
from ..models import Source, utcnow
from ..services import bus, icons, ingest, presets, strangers
from ..services import sources as sources_service

logger = logging.getLogger("nexsift.sources")

router = APIRouter(prefix="/api/sources", tags=["sources"])


class SourceIn(BaseModel):
    preset: str = Field(max_length=32)
    name: str = Field(default="", max_length=80)
    #: Syslog only: the host name the device sends as.
    hostname: str = Field(default="", max_length=128)
    #: ntfy and email only: use this topic or mail name instead of a generated one.
    key: str = Field(default="", max_length=64)


class SourceEdit(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    #: Left out: the icon stays. Empty: back to the two letters.
    icon: str | None = Field(default=None, max_length=icons.OWN_MAX)
    #: Left out: stays. What tapping a push to ntfy opens.
    tap: Literal["link", "nexsift"] | None = None


class MuteIn(BaseModel):
    #: 0 lifts the mute.
    minutes: int = Field(ge=0, le=60 * 24 * 30)


def _get(db: DbSession, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise fehler("not_found", "Source not found.", 404)
    return source


@router.get("/presets", summary="What can be added")
def list_presets(account: CurrentAccount) -> list[dict[str, str]]:
    return [{"key": key, **value} for key, value in presets.PRESETS.items()]


@router.get("", summary="All sources")
def list_sources(account: CurrentAccount, db: DbSession) -> list[dict[str, Any]]:
    return [sources_service.view(db, row) for row in db.scalars(select(Source).order_by(Source.name))]


@router.get("/strangers", summary="Senders knocking on a door no source answers")
def list_strangers(account: CurrentAccount) -> list[dict[str, Any]]:
    return strangers.listing()


@router.post("", status_code=201, summary="Add a source from a preset")
def create(payload: SourceIn, request: Request, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    try:
        source = sources_service.create(db, payload.preset, payload.name, payload.hostname, payload.key)
    except sources_service.SourceError as error:
        raise fehler(error.code, str(error), error.status) from error
    if source.match_key:
        protocol, _, key = source.match_key.partition(":")
        strangers.forget(protocol, key)
    # Name, preset and door only: the token and the topic are the permission to send.
    logger.info("Source created id=%s name=%s kind=%s door=%s", source.id, source.name, source.kind, source.protocol)
    bus.publish("source", id=source.id)
    return {
        **sources_service.view(db, source),
        "connection": sources_service.connection(db, source, request.url.hostname or ""),
    }


@router.get("/{source_id}", summary="One source with what to enter in the sender")
def read(source_id: int, request: Request, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    source = _get(db, source_id)
    return {
        **sources_service.view(db, source),
        "connection": sources_service.connection(db, source, request.url.hostname or ""),
    }


@router.put("/{source_id}", summary="Rename, pick an icon")
def rename(source_id: int, payload: SourceEdit, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    source = _get(db, source_id)
    if payload.icon is not None:
        try:
            source.icon = icons.normalize(payload.icon)
        except icons.IconError as error:
            raise fehler("icon_invalid", str(error), 422) from error
    if payload.tap is not None:
        source.tap = payload.tap
    source.name = " ".join(payload.name.split())[:80]
    db.commit()
    # Not the icon itself: an own address may carry a token.
    logger.info("Source changed id=%s name=%s icon=%s", source.id, source.name, "yes" if source.icon else "no")
    bus.publish("source", id=source.id)
    return sources_service.view(db, source)


@router.get("/{source_id}/icon", summary="The source's icon, fetched by nexsift", response_class=Response)
async def icon(source_id: int, account: CurrentAccount, db: DbSession) -> Response:
    source = _get(db, source_id)
    found = await icons.fetch(source.icon)
    if found is None:
        raise fehler("icon_unavailable", "The icon could not be loaded.", 404)
    data, kind = found
    return Response(
        data,
        media_type=kind,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post("/{source_id}/mute", summary="Mute for a while: messages arrive, nothing is pushed")
def mute(source_id: int, payload: MuteIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    source = _get(db, source_id)
    source.muted_until = utcnow() + timedelta(minutes=payload.minutes) if payload.minutes else None
    db.commit()
    logger.info("Source muted id=%s name=%s minutes=%s", source.id, source.name, payload.minutes)
    bus.publish("source", id=source.id)
    return sources_service.view(db, source)


@router.post("/{source_id}/token", summary="New token; the old one stops working at once")
def renew(source_id: int, request: Request, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    source = _get(db, source_id)
    try:
        sources_service.renew_token(db, source)
    except sources_service.SourceError as error:
        raise fehler(error.code, str(error), error.status) from error
    logger.info("Source got a new token id=%s name=%s", source.id, source.name)
    return {
        **sources_service.view(db, source),
        "connection": sources_service.connection(db, source, request.url.hostname or ""),
    }


@router.post("/{source_id}/test", summary="Put a test message into the inbox, as if the sender had sent it")
def test(source_id: int, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    source = _get(db, source_id)
    incoming = Incoming(
        title=f"Test message for {source.name}",
        body=(
            "Sent from the sources page. If you see this in the inbox, nexsift works; "
            "the real sender still has to be set up."
        ),
        raw='{"test": true}',
        group_key="nexsift-test",
    )
    changed = ingest.accept(db, source, incoming, {}, test=True)
    return {"threads": changed}


@router.delete("/{source_id}", status_code=204, summary="Delete the source with all its messages and rules")
def delete(source_id: int, account: CurrentAccount, db: DbSession) -> None:
    source = _get(db, source_id)
    name = source.name
    db.delete(source)
    db.commit()
    logger.info("Source deleted id=%s name=%s", source_id, name)
    bus.publish("source", id=source_id)
