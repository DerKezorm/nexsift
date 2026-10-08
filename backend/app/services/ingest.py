"""From an incoming message to a line in the inbox.

For every event the doors hand over:

1. The source is marked as seen; an unrecognized format counts up its streak, a recognized one resets it.
2. The rules run. "drop" ends here: counted, not stored.
3. An all-clear (Uptime Kuma UP, or a rule with "resolves") closes the open problem of the same kind instead of
   opening a line of its own.
4. The event joins the open thread of the same source and group key, or opens a new one. A thread takes more
   events while it is open and the last one is younger than the bundle window. An unresolved critical thread
   stays open for its kind until it is resolved or archived: a problem stays one problem.
5. Above the per-source limit, events are only counted on their thread: the inbox stays usable when a container
   loops.
6. The push service decides what reaches the phone.

Every step leaves the message in the inbox unless a rule says "drop". An adapter that did not understand the
format still delivered title and text.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.base import Incoming
from ..adapters.kinds import refine, shape
from ..models import ARCHIVED, CRIT, INFO, RANK, ROUTINE_KEY, UNREAD, Event, Source, Thread, utcnow
from . import bus, icons, push, rules, settings_service

logger = logging.getLogger("nexsift.ingest")
#: What a message said; written at the level ``trace`` only (see ``services/logs.py``).
content_log = logging.getLogger("nexsift.content")

#: The group key of the line that collects a source's overflow when it sends too much of everything.
OVERFLOW_KEY = "__overflow__"


class _Counter:
    """Events per source in the last minute, in memory. Resets with a restart, which is fine: it is a brake."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[int, deque[float]] = {}

    def hit(self, source_id: int) -> int:
        now = time.monotonic()
        with self._lock:
            window = self._seen.setdefault(source_id, deque())
            window.append(now)
            while window and window[0] < now - 60:
                window.popleft()
            return len(window)

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


counter = _Counter()

#: One message at a time. The doors run in several threads; without this, two messages of the same kind that
#: arrive in the same instant both find no open thread and each opens one (seen with two syslog lines).
_ingest_lock = threading.Lock()


def accept(db: Session, source: Source, incoming: Incoming, payload: dict, *, test: bool = False) -> list[int]:
    """Refines what a door made and stores it. Returns the ids of the threads that changed.

    ``test``: the test button on the sources page. Skips the adapter and leaves the source's counters alone, so a
    test never hides that the real sender has not been heard from yet."""
    with _ingest_lock:
        return _accept(db, source, incoming, payload, test=test)


def _accept(db: Session, source: Source, incoming: Incoming, payload: dict, *, test: bool) -> list[int]:
    changed: list[int] = []
    # Read again inside the lock: the caller loaded the source before waiting for it, and two messages that
    # arrived together would otherwise both count from the same stale number (seen with syslog, 01.10.2026).
    db.refresh(source)
    events = [incoming.clean()] if test else refine(source.kind, incoming, payload)
    now = utcnow()
    if not test:
        source.last_seen_at = now
    for item in events:
        if test:
            pass
        elif item.recognized:
            source.unrecognized_streak = 0
        else:
            source.unrecognized_streak += 1
            source.last_unrecognized_at = now
        if not test:
            source.count_total += 1
        thread_id = _store(db, source, item)
        if thread_id is not None and thread_id not in changed:
            changed.append(thread_id)
        content_log.debug(
            "Message from source_id=%s priority=%s title=%r body=%r",
            source.id,
            item.priority,
            item.title[:200],
            item.body[:500],
        )
    db.commit()
    logger.debug(
        "Taken in source_id=%s door=%s events=%s threads=%s test=%s",
        source.id,
        source.protocol,
        len(events),
        changed,
        test,
    )
    for thread_id in changed:
        bus.publish("thread", id=thread_id)
    bus.publish("source", id=source.id)
    return changed


def _open_thread(db: Session, source_id: int, group_key: str, window: timedelta) -> Thread | None:
    candidate = db.scalar(
        select(Thread)
        .where(
            Thread.source_id == source_id,
            Thread.group_key == group_key,
            Thread.resolved_at.is_(None),
            Thread.deleted_at.is_(None),
            Thread.state != ARCHIVED,
        )
        .order_by(Thread.last_at.desc())
        .limit(1)
    )
    if candidate is None:
        return None
    if candidate.priority == CRIT:
        return candidate
    return candidate if utcnow() - candidate.last_at <= window else None


def _store(db: Session, source: Source, item: Incoming) -> int | None:
    outcome = rules.evaluate(rules.ordered(db), source.id, item.title, item.body)
    actions = outcome.actions
    if actions.get("drop"):
        return None
    # The sender's own icon first, then the rule's (several apps behind one source), then the source's in push.py.
    if actions.get("icon") and not item.icon:
        item.icon = icons.public_url(str(actions["icon"]))
    priority = actions.get("priority") or item.priority
    if actions.get("group_key"):
        group_key = rules.fill(actions["group_key"], item.fields)
    elif item.group_key:
        group_key = item.group_key
    elif priority == INFO and not actions.get("title_template"):
        group_key = ROUTINE_KEY
    else:
        group_key = shape(item.title)
    resolves = rules.fill(actions["resolves"], item.fields) if actions.get("resolves") else item.resolves
    window = timedelta(minutes=int(settings_service.get(db, "bundle_minutes")))
    now = utcnow()

    if resolves:
        problem = db.scalar(
            select(Thread)
            .where(
                Thread.source_id == source.id,
                Thread.group_key == resolves,
                Thread.resolved_at.is_(None),
                Thread.deleted_at.is_(None),
            )
            .order_by(Thread.last_at.desc())
            .limit(1)
        )
        if problem is not None:
            _add_event(db, problem, item, priority=item.priority)
            problem.resolved_at = now
            problem.resolved_by = item.title[:300]
            problem.rule_names = _merge_names(problem.rule_names, outcome.matched)
            db.flush()
            push.on_resolved(db, problem)
            return problem.id

    thread = _open_thread(db, source.id, group_key, window)
    over = counter.hit(source.id) > int(settings_service.get(db, "throttle_per_minute"))
    if over:
        target = thread or _open_thread(db, source.id, OVERFLOW_KEY, timedelta(hours=1))
        if target is not None:
            target.throttled_count += 1
            target.last_at = now
            return target.id
        # The first overflow message of a flood gets a line of its own that counts the rest.
        group_key = OVERFLOW_KEY
        item.title = f"{source.name}: too many messages"
        item.body = "More messages than the limit per minute arrived; nexsift counts them here and stores none of them."

    is_new = thread is None
    if thread is None:
        thread = Thread(
            source_id=source.id,
            group_key=group_key,
            title=item.title,
            title_template=str(actions.get("title_template", "")),
            priority=priority,
            state=UNREAD,
            first_at=now,
            last_at=now,
            push_mode=str(actions.get("push", "")),
            rule_names=list(outcome.matched),
            icon=str(actions.get("icon", "")),
            targets=list(actions["targets"]) if actions.get("targets") else None,
            min_priority=str(actions.get("min_priority", "")),
        )
        db.add(thread)
        db.flush()
    else:
        if RANK[priority] > RANK[thread.priority]:
            thread.priority = priority
        if actions.get("title_template"):
            thread.title_template = str(actions["title_template"])
        if actions.get("push"):
            thread.push_mode = str(actions["push"])
        if actions.get("icon"):
            thread.icon = str(actions["icon"])
        if actions.get("targets"):
            thread.targets = list(actions["targets"])
        if actions.get("min_priority"):
            thread.min_priority = str(actions["min_priority"])
        thread.rule_names = _merge_names(thread.rule_names, outcome.matched)
        # New news: back to unread, so it is not missed under a line that was already read.
        if thread.state != UNREAD:
            thread.state = UNREAD
    event = _add_event(db, thread, item, priority=priority)
    # A bundle title only makes sense for a bundle: a single event keeps its own words ("Updated redis", not
    # "1 containers updated").
    if thread.title_template and thread.event_count > 1:
        thread.title = thread.title_template.replace("{count}", str(thread.event_count))[:300]
    elif not is_new:
        thread.title = item.title
    db.flush()
    push.on_event(db, source, thread, event, is_new=is_new)
    return thread.id


def _add_event(db: Session, thread: Thread, item: Incoming, priority: str) -> Event:
    event = Event(
        thread_id=thread.id,
        title=item.title,
        body=item.body,
        priority=priority,
        links=item.links,
        raw=item.raw,
        recognized=item.recognized,
        texts=item.texts or None,
        icon=item.icon,
    )
    db.add(event)
    thread.event_count += 1
    thread.last_at = utcnow()
    return event


def _merge_names(existing: list | None, new: list[str]) -> list[str]:
    names = list(existing or [])
    for name in new:
        if name not in names:
            names.append(name)
    return names[:10]
