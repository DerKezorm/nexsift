"""Reading threads for the interface: the list, one thread with its events, counts for the side bar."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from ..models import ARCHIVED, CRIT, READ, ROUTINE_KEY, UNREAD, Delivery, Event, Source, Target, Thread, utcnow

VIEWS = ("inbox", "unread", "crit", "archived")
PAGE = 100
#: Deleted threads stay restorable this long; then the housekeeping removes them for good.
UNDO_MINUTES = 10
#: ``resolved_by`` of a problem closed in the interface; the interface shows it in its own words.
BY_HAND = "Marked as done by hand"


def _view_filter(query: Select, view: str) -> Select:
    query = query.where(Thread.deleted_at.is_(None))
    if view == "archived":
        return query.where(Thread.state == ARCHIVED)
    query = query.where(Thread.state != ARCHIVED)
    if view == "unread":
        return query.where(Thread.state == UNREAD)
    if view == "crit":
        return query.where(Thread.priority == CRIT, Thread.resolved_at.is_(None))
    return query


def listing(db: Session, view: str, source_id: int | None, text: str, before: str | None) -> dict[str, Any]:
    query = _view_filter(select(Thread), view)
    if source_id:
        query = query.where(Thread.source_id == source_id)
    needle = text.strip()
    if needle:
        like = f"%{needle[:100]}%"
        matching_events = select(Event.thread_id).where(or_(Event.title.ilike(like), Event.body.ilike(like)))
        query = query.where(or_(Thread.title.ilike(like), Thread.id.in_(matching_events)))
    if before:
        try:
            last_at, last_id = before.split("_", 1)
            from datetime import datetime

            stamp = datetime.fromisoformat(last_at)
            query = query.where(or_(Thread.last_at < stamp, (Thread.last_at == stamp) & (Thread.id < int(last_id))))
        except ValueError:
            pass
    rows = list(db.scalars(query.order_by(Thread.last_at.desc(), Thread.id.desc()).limit(PAGE + 1)))
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    latest = _latest_events(db, [row.id for row in rows])
    pushed = _pushed(db, [row.id for row in rows])
    items = [summary(row, latest.get(row.id), row.id in pushed) for row in rows]
    cursor = f"{rows[-1].last_at.isoformat()}_{rows[-1].id}" if more and rows else None
    return {"items": items, "next": cursor}


def _latest_events(db: Session, ids: list[int]) -> dict[int, Event]:
    if not ids:
        return {}
    newest = (
        select(Event.thread_id, func.max(Event.id).label("id"))
        .where(Event.thread_id.in_(ids))
        .group_by(Event.thread_id)
        .subquery()
    )
    return {event.thread_id: event for event in db.scalars(select(Event).join(newest, Event.id == newest.c.id))}


def _pushed(db: Session, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return set(
        db.scalars(select(Delivery.thread_id).where(Delivery.thread_id.in_(ids), Delivery.status == "sent").distinct())
    )


def _preview(latest: Event | None, routine: bool) -> str:
    if latest is None:
        return ""
    if routine and latest.body:
        return f"{latest.title}: {latest.body}"[:200]
    return (latest.body or latest.title)[:200]


def summary(thread: Thread, latest: Event | None, pushed: bool) -> dict[str, Any]:
    routine = thread.group_key == ROUTINE_KEY and thread.event_count > 1
    return {
        "id": thread.id,
        "source_id": thread.source_id,
        "title": thread.title,
        "priority": thread.priority,
        "state": thread.state,
        "event_count": thread.event_count,
        "first_at": thread.first_at.isoformat(),
        "last_at": thread.last_at.isoformat(),
        "resolved_at": thread.resolved_at.isoformat() if thread.resolved_at else None,
        "resolved_by": thread.resolved_by,
        "throttled_count": thread.throttled_count,
        "pushed": pushed,
        # A routine line holds different things; its preview names the latest one by its title.
        "routine": routine,
        "preview": _preview(latest, routine),
        "links": latest.links if latest else [],
        # Words nexsift wrote itself, for the interface to show in its language; the title only when it came
        # from that event (a rule's bundle title did not).
        "texts": latest.texts if latest is not None and latest.texts else None,
        "title_from_texts": bool(latest is not None and latest.texts and thread.title == latest.title),
    }


def detail(db: Session, thread: Thread, limit: int = 200) -> dict[str, Any]:
    events = list(db.scalars(select(Event).where(Event.thread_id == thread.id).order_by(Event.id.desc()).limit(limit)))
    deliveries = list(
        db.execute(
            select(Delivery, Target.name, Target.kind)
            .join(Target, Target.id == Delivery.target_id)
            .where(Delivery.thread_id == thread.id)
            .order_by(Delivery.id)
        )
    )
    data = summary(thread, events[0] if events else None, any(row[0].status == "sent" for row in deliveries))
    data["rule_names"] = thread.rule_names or []
    data["push_mode"] = thread.push_mode
    data["window_until"] = thread.window_until.isoformat() if thread.window_until else None
    data["events"] = [
        {
            "id": event.id,
            "received_at": event.received_at.isoformat(),
            "title": event.title,
            "body": event.body,
            "priority": event.priority,
            "links": event.links or [],
            "raw": event.raw,
            "recognized": event.recognized,
            "texts": event.texts or None,
        }
        for event in events
    ]
    data["deliveries"] = [
        {
            "id": delivery.id,
            "target": name,
            "target_kind": kind,
            "kind": delivery.kind,
            "status": delivery.status,
            "attempts": delivery.attempts,
            "created_at": delivery.created_at.isoformat(),
            "sent_at": delivery.sent_at.isoformat() if delivery.sent_at else None,
            "last_error": delivery.last_error,
        }
        for delivery, name, kind in deliveries
    ]
    return data


def counts(db: Session) -> dict[str, Any]:
    views = {view: int(db.scalar(_view_filter(select(func.count()).select_from(Thread), view)) or 0) for view in VIEWS}
    unread = dict(
        db.execute(
            select(Thread.source_id, func.count())
            .where(Thread.state == UNREAD, Thread.deleted_at.is_(None))
            .group_by(Thread.source_id)
        ).all()
    )
    return {"views": views, "unread_by_source": {str(key): value for key, value in unread.items()}}


def set_state(db: Session, ids: list[int], state: str) -> list[int]:
    changed = []
    for thread in db.scalars(select(Thread).where(Thread.id.in_(ids[:500]), Thread.deleted_at.is_(None))):
        thread.state = state
        changed.append(thread.id)
    db.commit()
    return changed


def resolve(db: Session, ids: list[int]) -> list[int]:
    """Close open problems by hand, as if the all-clear had come. Already closed ones stay as they were."""
    now = utcnow()
    changed = []
    query = select(Thread).where(Thread.id.in_(ids[:500]), Thread.deleted_at.is_(None), Thread.resolved_at.is_(None))
    for thread in db.scalars(query):
        thread.resolved_at = now
        thread.resolved_by = BY_HAND
        changed.append(thread.id)
    db.commit()
    return changed


def resolve_all(db: Session, source_id: int | None) -> list[int]:
    """Everything in "critical open", optionally of one source."""
    query = _view_filter(select(Thread.id), "crit")
    if source_id:
        query = query.where(Thread.source_id == source_id)
    return resolve(db, list(db.scalars(query.limit(500))))


def reopen(db: Session, ids: list[int]) -> list[int]:
    """Undo for ``resolve``: only what was closed by hand opens again, an all-clear from the sender stays."""
    changed = []
    query = select(Thread).where(Thread.id.in_(ids[:500]), Thread.deleted_at.is_(None), Thread.resolved_by == BY_HAND)
    for thread in db.scalars(query):
        thread.resolved_at = None
        thread.resolved_by = ""
        changed.append(thread.id)
    db.commit()
    return changed


def delete(db: Session, ids: list[int]) -> list[int]:
    now = utcnow()
    changed = []
    for thread in db.scalars(select(Thread).where(Thread.id.in_(ids[:500]), Thread.deleted_at.is_(None))):
        thread.deleted_at = now
        changed.append(thread.id)
    db.commit()
    return changed


def restore(db: Session, ids: list[int]) -> list[int]:
    changed = []
    for thread in db.scalars(select(Thread).where(Thread.id.in_(ids[:500]), Thread.deleted_at.is_not(None))):
        thread.deleted_at = None
        changed.append(thread.id)
    db.commit()
    return changed


def mark_all_read(db: Session, view: str, source_id: int | None) -> list[int]:
    query = _view_filter(select(Thread), view).where(Thread.state == UNREAD)
    if source_id:
        query = query.where(Thread.source_id == source_id)
    changed = []
    for thread in db.scalars(query):
        thread.state = READ
        changed.append(thread.id)
    db.commit()
    return changed


def purge_deleted(db: Session) -> int:
    cutoff = utcnow() - timedelta(minutes=UNDO_MINUTES)
    rows = list(db.scalars(select(Thread).where(Thread.deleted_at.is_not(None), Thread.deleted_at < cutoff)))
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def source_names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Source.id, Source.name)).all())
