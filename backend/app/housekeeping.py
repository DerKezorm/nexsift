"""Every few minutes: remove what is past its time.

* Deleted threads after the undo time.
* Archived threads after ``archive_days``, all others after ``retention_days``. An unresolved critical thread
  stays, however old: a problem nobody looked at is not solved by forgetting it.
* Raw data after ``raw_days`` (the events stay, only what the sender sent verbatim goes).
* Deliveries after 30 days, expired browser sessions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, or_, select, update

from .db import SessionLocal
from .models import ARCHIVED, CRIT, Delivery, Event, Thread, utcnow
from .security import purge_sessions
from .services import settings_service, threads

logger = logging.getLogger("nexsift.housekeeping")

INTERVAL_SECONDS = 300


def run_once() -> None:
    with SessionLocal() as db:
        threads.purge_deleted(db)
        now = utcnow()
        keep = int(settings_service.get(db, "retention_days"))
        keep_archived = int(settings_service.get(db, "archive_days"))
        keep_raw = int(settings_service.get(db, "raw_days"))
        old = select(Thread.id).where(
            Thread.deleted_at.is_(None),
            or_(
                (Thread.state == ARCHIVED) & (Thread.last_at < now - timedelta(days=keep_archived)),
                (Thread.state != ARCHIVED)
                & (Thread.last_at < now - timedelta(days=keep))
                & ~((Thread.priority == CRIT) & Thread.resolved_at.is_(None)),
            ),
        )
        removed = db.execute(delete(Thread).where(Thread.id.in_(old))).rowcount or 0
        db.execute(
            update(Event).where(Event.raw != "", Event.received_at < now - timedelta(days=keep_raw)).values(raw="")
        )
        db.execute(delete(Delivery).where(Delivery.created_at < now - timedelta(days=30)))
        db.commit()
        purge_sessions(db)
        if removed:
            logger.info("Housekeeping removed %s old threads", removed)


async def run_forever(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.get_running_loop().run_in_executor(None, run_once)
        except Exception:
            logger.exception("Housekeeping failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)
        except TimeoutError:
            continue
