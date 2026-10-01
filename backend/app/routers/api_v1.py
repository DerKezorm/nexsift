"""What a dashboard may read with an API key: the numbers of the inbox and its newest lines. Nothing else.

⚠️ Only the Authorization header, never the cookie. These addresses are built for other programs; a signed-in
browser does not get in here, so no foreign page can read them through someone's session. And a key opens none
of the other addresses.

⚠️ No message text, no sender address, no token in any answer. A dashboard is often seen by guests; the title of a
line says what happened, the details stay in nexsift.

``POST /api/v1/hook/<token>`` (the own webhook, ``routers/ingress.py``) shares the prefix; it is a door for
senders, not part of this read API, and takes no API key.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from .. import __version__
from ..deps import DbSession, client_ip
from ..meldungen import fehler
from ..models import ARCHIVED, CRIT, UNREAD, WARN, ApiKey, Event, Source, Target, Thread
from ..services import api_keys

logger = logging.getLogger("nexsift.api")

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


def key_in_header(request: Request, db: DbSession) -> ApiKey:
    """A valid key, asked on every request so the switch and a deletion act at once."""
    kind, _, value = request.headers.get("authorization", "").partition(" ")
    if kind.lower() != "bearer" or not value.strip():
        raise fehler("api_key_missing", "This address needs an API key in the Authorization header.", 401)
    if not api_keys.allowed(db):
        raise fehler("api_keys_off", "API keys are switched off in this installation.", 403)
    found = api_keys.find(db, value.strip())
    if found is None:
        logger.info("API request refused: unknown or withdrawn key from=%s", client_ip(request))
        raise fehler("api_key_invalid", "This API key is not valid.", 401)
    return found


ValidKey = Annotated[ApiKey, Depends(key_in_header)]


def _today_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _count(db: DbSession, *conditions: Any) -> int:
    query = select(func.count()).select_from(Thread).where(Thread.deleted_at.is_(None), Thread.state != ARCHIVED)
    return int(db.scalar(query.where(*conditions)) or 0)


@router.get("/status", summary="Version and the numbers of the inbox")
def status(key: ValidKey, db: DbSession) -> dict[str, Any]:
    since = _today_start()
    last = db.scalar(select(func.max(Event.received_at)))
    return {
        "version": __version__,
        "unread": _count(db, Thread.state == UNREAD),
        "critical_open": _count(db, Thread.priority == CRIT, Thread.resolved_at.is_(None)),
        "warnings_unread": _count(db, Thread.priority == WARN, Thread.state == UNREAD),
        "lines": _count(db),
        "messages_today": int(db.scalar(select(func.count()).select_from(Event).where(Event.received_at >= since))),
        "sources": int(db.scalar(select(func.count()).select_from(Source)) or 0),
        "targets_failing": int(
            db.scalar(select(func.count()).select_from(Target).where(Target.enabled, Target.last_error != "")) or 0
        ),
        "last_message_at": last.isoformat() if last else None,
    }


@router.get("/threads", summary="The newest lines of the inbox, newest first")
def threads(
    key: ValidKey,
    db: DbSession,
    view: Annotated[str, Query(pattern="^(inbox|unread|crit)$")] = "inbox",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, Any]]:
    query = (
        select(Thread, Source.name)
        .join(Source, Source.id == Thread.source_id)
        .where(Thread.deleted_at.is_(None), Thread.state != ARCHIVED)
    )
    if view == "unread":
        query = query.where(Thread.state == UNREAD)
    elif view == "crit":
        query = query.where(Thread.priority == CRIT, Thread.resolved_at.is_(None))
    rows = db.execute(query.order_by(Thread.last_at.desc(), Thread.id.desc()).limit(limit))
    return [
        {
            "id": thread.id,
            "title": thread.title,
            "source": source,
            "priority": thread.priority,
            "state": thread.state,
            "count": thread.event_count,
            "first_at": thread.first_at.isoformat(),
            "last_at": thread.last_at.isoformat(),
            "resolved": thread.resolved_at is not None,
        }
        for thread, source in rows
    ]
