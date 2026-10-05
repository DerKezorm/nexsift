"""What reaches the phone, and getting it there.

Decisions happen when an event is stored (``on_event``, ``on_resolved``) and at the end of bundle windows
(``due_windows``); they only write ``Delivery`` rows. The worker (``run_forever``) sends what is due and tries
again with growing pauses when a target is unreachable. So a slow or dead ntfy never slows down a door.

Push behaviour per thread (from a rule, else the setting):

* ``immediate``: the first event of a thread goes out at once. More of the same are counted quietly; when the
  bundle window ends and there were more, one follow-up says how many.
* ``window``: nothing at once; one push at the end of the window with the count.
* ``single``: every event on its own.
* ``never``: stays in the inbox.

A target takes a push when the priority reaches its minimum. Quiet hours hold back everything below critical.
The storm guard counts first pushes across all sources: from N within M minutes on, the rest of that stretch
becomes one summary per target, so a power cut is one message and not twenty.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, time, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..db import SessionLocal
from ..models import CRIT, INFO, RANK, WARN, Delivery, Event, Source, Target, Thread, utcnow
from . import bus, icons, settings_service, texts, webpush
from . import sources as sources_service

logger = logging.getLogger("nexsift.push")

TARGET_KINDS = ("ntfy", "gotify", "telegram", "pushover", "webhook", "apprise", "webpush")
#: Pauses between attempts; after the last one the delivery counts as failed and shows on the target.
RETRY_SECONDS = (30, 120, 600, 1800, 3600)
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
#: Tests set an ``httpx.MockTransport`` here.
transport_for_tests: httpx.BaseTransport | None = None

# The storm guard in memory: when the current storm ends and what it swallowed.
_storm_until: datetime | None = None
_storm_swallowed: list[tuple[str, str]] = []


def reset_for_tests() -> None:
    global _storm_until
    _storm_until = None
    _storm_swallowed.clear()


def _mode(db: Session, thread: Thread) -> str:
    return thread.push_mode or str(settings_service.get(db, "push_mode"))


def _targets(db: Session, priority: str) -> list[Target]:
    return [
        target
        for target in db.scalars(select(Target).where(Target.enabled.is_(True)))
        if RANK[priority] >= RANK[target.min_priority]
    ]


def _in_quiet_hours(target: Target, now: datetime | None = None) -> bool:
    if not target.quiet_from or not target.quiet_to:
        return False
    local = (now or datetime.now().astimezone()).astimezone().time()
    try:
        start = time.fromisoformat(target.quiet_from)
        end = time.fromisoformat(target.quiet_to)
    except ValueError:
        return False
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def _link(event: Event | None) -> str:
    if event is None or not event.links:
        return ""
    return str(event.links[0].get("url", ""))


def _icon(source: Source | None, event: Event | None) -> str:
    """The sender's own picture when it sent one, else the source's."""
    if event is not None and event.icon:
        return event.icon
    return icons.public_url(source.icon) if source is not None else ""


def _enqueue(
    db: Session,
    thread: Thread | None,
    kind: str,
    title: str,
    body: str,
    priority: str,
    link: str = "",
    *,
    send_as: str | None = None,
    icon: str = "",
) -> int:
    """``priority`` decides which targets get it; ``send_as`` how loud it arrives there (default: the same).
    Quiet hours hold back everything below critical, and all-clears too: good news does not wake anybody."""
    count = 0
    for target in _targets(db, priority):
        if (priority != CRIT or kind == "allclear") and _in_quiet_hours(target):
            continue
        db.add(
            Delivery(
                thread_id=thread.id if thread else None,
                target_id=target.id,
                kind=kind,
                title=title[:300],
                body=body[:2000],
                priority=send_as or priority,
                link=link,
                icon=icon,
            )
        )
        count += 1
    return count


def _storming(db: Session, now: datetime) -> bool:
    """Whether first pushes are being swallowed right now; starts a storm when too many went out lately."""
    global _storm_until
    if not settings_service.get(db, "storm_enabled"):
        return False
    if _storm_until is not None and now < _storm_until:
        return True
    minutes = int(settings_service.get(db, "storm_minutes"))
    recent = db.scalar(
        select(func.count(func.distinct(Delivery.thread_id))).where(
            Delivery.kind == "first", Delivery.created_at >= now - timedelta(minutes=minutes)
        )
    )
    if int(recent or 0) >= int(settings_service.get(db, "storm_count")):
        _storm_until = now + timedelta(minutes=minutes)
        logger.warning(
            "Storm guard: %s first pushes within %s minutes, bundling until %s", recent, minutes, _storm_until
        )
        return True
    return False


def _language(db: Session) -> str:
    return str(settings_service.get(db, "push_language") or texts.FALLBACK)


def _event_title(db: Session, event: Event) -> str:
    return texts.title(event.texts, _language(db)) or event.title


def _event_body(db: Session, event: Event) -> str:
    body = texts.body(event.texts, _language(db))
    return event.body if body is None else body


def _thread_title(db: Session, thread: Thread, event: Event | None = None) -> str:
    """The line's title in the push language, when nexsift worded it; a rule's bundle title stays as it is."""
    if event is None:
        event = db.scalar(select(Event).where(Event.thread_id == thread.id).order_by(Event.id.desc()).limit(1))
    if event is not None and event.texts and event.title == thread.title:
        return _event_title(db, event)
    return thread.title


def _first(db: Session, source: Source, thread: Thread, event: Event) -> None:
    now = utcnow()
    title = _thread_title(db, thread, event)
    if _storming(db, now):
        _storm_swallowed.append((source.name, title))
        thread.pushed = True
        thread.since_push = 0
        return
    body = _event_body(db, event)
    if _enqueue(
        db, thread, "first", f"{source.name}: {title}", body, thread.priority, _link(event), icon=_icon(source, event)
    ):
        thread.pushed = True
        thread.since_push = 0


def on_event(db: Session, source: Source, thread: Thread, event: Event, *, is_new: bool) -> None:
    if sources_service.is_muted(source):
        return
    mode = _mode(db, thread)
    if mode == "never" or not _targets(db, thread.priority):
        return
    window = timedelta(minutes=int(settings_service.get(db, "bundle_minutes")))
    if mode == "single":
        _enqueue(
            db,
            thread,
            "first",
            f"{source.name}: {_event_title(db, event)}",
            _event_body(db, event),
            event.priority,
            _link(event),
            icon=_icon(source, event),
        )
        thread.pushed = True
        return
    if mode == "window":
        if thread.window_until is None or thread.pushed:
            thread.window_until = thread.first_at + window if not thread.pushed else utcnow() + window
            thread.pushed = False
        thread.since_push += 1
        return
    # immediate
    if not thread.pushed:
        _first(db, source, thread, event)
        thread.window_until = utcnow() + window
        return
    thread.since_push += 1
    if thread.window_until is None or thread.window_until < utcnow():
        thread.window_until = utcnow() + window


def on_resolved(db: Session, thread: Thread) -> None:
    """The all-clear goes where the alarm went: if the problem was pushed, its end is pushed too."""
    if not thread.pushed:
        return
    source = db.get(Source, thread.source_id)
    name = source.name if source else "nexsift"
    # Same targets as the alarm, but not as loud: found with a real ntfy and Gotify on 01.10.2026, where the
    # all-clear arrived with the alarm's top priority.
    language = _language(db)
    took = _took((thread.resolved_at or utcnow()) - thread.first_at, language)
    # The all-clear is the newest event; when nexsift worded it, it says so in the push language too.
    latest = db.scalar(select(Event).where(Event.thread_id == thread.id).order_by(Event.id.desc()).limit(1))
    said = _event_title(db, latest) if latest is not None and latest.title == thread.resolved_by else ""
    _enqueue(
        db,
        thread,
        "allclear",
        f"{name}: {said or thread.resolved_by or texts.say('push.resolved', language)}",
        texts.say("push.resolvedAfter", language, took=took),
        thread.priority,
        send_as=INFO,
        icon=_icon(source, latest),
    )
    thread.window_until = None
    thread.since_push = 0


def _took(span: timedelta, language: str = texts.FALLBACK) -> str:
    minutes = max(1, round(span.total_seconds() / 60))
    if minutes < 120:
        return texts.say("push.minutes", language, count=minutes)
    hours = minutes / 60
    if hours < 48:
        return texts.say("push.hours", language, count=round(hours))
    return texts.say("push.days", language, count=round(hours / 24))


def due_windows(db: Session) -> int:
    """Follow-ups and window pushes whose time has come. Called by the worker."""
    now = utcnow()
    count = 0
    for thread in db.scalars(
        select(Thread).where(Thread.window_until.is_not(None), Thread.window_until <= now, Thread.deleted_at.is_(None))
    ):
        source = db.get(Source, thread.source_id)
        name = source.name if source else "nexsift"
        mode = _mode(db, thread)
        language = _language(db)
        if thread.since_push > 0 and not thread.resolved_at:
            latest = db.scalar(select(Event).where(Event.thread_id == thread.id).order_by(Event.id.desc()).limit(1))
            title = f"{name}: {_thread_title(db, thread, latest)}"
            icon = _icon(source, latest)
            if mode == "window" and not thread.pushed:
                body = texts.say("push.messages", language, count=thread.since_push)
                count += _enqueue(db, thread, "first", title, body, thread.priority, icon=icon)
            elif mode == "immediate":
                body = texts.say("push.more", language, count=thread.since_push)
                count += _enqueue(db, thread, "followup", title, body, thread.priority, icon=icon)
            thread.pushed = True
        thread.since_push = 0
        thread.window_until = None
    global _storm_until
    if _storm_until is not None and now >= _storm_until:
        if _storm_swallowed:
            sources_hit = sorted({name for name, _ in _storm_swallowed})
            lines = "\n".join(f"{name}: {title}" for name, title in _storm_swallowed[:15])
            title = texts.say("push.storm", _language(db), count=len(_storm_swallowed), sources=len(sources_hit))
            count += _enqueue(db, None, "storm", title, lines, CRIT)
            _storm_swallowed.clear()
        _storm_until = None
    db.commit()
    return count


# --------------------------------------------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------------------------------------------


def target_config(target: Target) -> dict[str, Any]:
    try:
        return json.loads(crypto.decrypt_secret(target.config_enc) or "{}")
    except ValueError:
        return {}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=transport_for_tests, follow_redirects=False)


NTFY_PRIORITY = {CRIT: "5", WARN: "4"}
GOTIFY_PRIORITY = {CRIT: 8, WARN: 5}
#: Pushover's 2 (emergency) repeats until someone acknowledges it; nexsift keeps to 1, which already sounds
#: through the quiet hours set in the Pushover app. Info arrives without a sound.
PUSHOVER_PRIORITY = {CRIT: 1, WARN: 0}
PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


async def send(
    target: Target,
    title: str,
    body: str,
    priority: str,
    link: str = "",
    kind: str = "",
    thread_id: int | None = None,
    icon: str = "",
) -> None:
    """One message to one target. Raises ``PushError`` with a short, readable reason. ``icon`` reaches ntfy and web
    push; Gotify, Telegram and Pushover have no picture per message."""
    config = target_config(target)
    if target.kind == "webpush":
        await _send_webpush(config, title, body, priority, kind, thread_id, icon)
        return
    url = str(config.get("url", "")).strip()
    token = str(config.get("token", "")).strip()
    async with _client() as client:
        try:
            if target.kind == "ntfy":
                headers = {"Title": _header(title), "Priority": NTFY_PRIORITY.get(priority, "3"), "Tags": "nexsift"}
                if priority == CRIT:
                    headers["Tags"] = "rotating_light,nexsift"
                elif kind == "allclear":
                    headers["Tags"] = "white_check_mark,nexsift"
                if link:
                    headers["Click"] = link
                if icon:
                    headers["Icon"] = _header(icon)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                response = await client.post(url, content=(body or title).encode("utf-8"), headers=headers)
            elif target.kind == "gotify":
                payload: dict[str, Any] = {
                    "title": title,
                    "message": body or title,
                    "priority": GOTIFY_PRIORITY.get(priority, 2),
                }
                if link:
                    payload["extras"] = {"client::notification": {"click": {"url": link}}}
                response = await client.post(
                    f"{url.rstrip('/')}/message", json=payload, headers={"X-Gotify-Key": token}
                )
            elif target.kind == "telegram":
                chat = str(config.get("chat_id", "")).strip()
                text = f"{title}\n\n{body}".strip() + (f"\n{link}" if link else "")
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
                )
            elif target.kind == "pushover":
                form = {
                    "token": token,
                    "user": str(config.get("user", "")).strip(),
                    "title": title[:250],
                    "message": (body or title)[:1024],
                    "priority": str(0 if kind == "allclear" else PUSHOVER_PRIORITY.get(priority, -1)),
                }
                if link:
                    form["url"] = link[:512]
                response = await client.post(PUSHOVER_URL, data=form)
                if 400 <= response.status_code < 500:
                    raise PushError(_pushover_reason(response))
            elif target.kind == "apprise":
                kind = {CRIT: "failure", WARN: "warning"}.get(priority, "info")
                response = await client.post(url, json={"title": title, "body": body or title, "type": kind})
            elif target.kind == "webhook":
                response = await client.post(
                    url, json={"title": title, "message": body, "priority": priority, "link": link, "from": "nexsift"}
                )
            else:
                raise PushError("unknown target kind")
        except httpx.TimeoutException as error:
            raise PushError("no answer within 10 seconds") from error
        except httpx.HTTPError as error:
            raise PushError(f"not reachable ({type(error).__name__})") from error
    if response.status_code >= 400:
        raise PushError(f"answered HTTP {response.status_code}")


def _pushover_reason(response: httpx.Response) -> str:
    """Pushover says in plain words what is wrong (a wrong token, an unknown user key); the values are not in it."""
    try:
        errors = response.json().get("errors") or []
    except ValueError:
        errors = []
    said = "; ".join(str(error) for error in errors if isinstance(error, str))[:200]
    return f"Pushover: {said}" if said else f"answered HTTP {response.status_code}"


def _header(text: str) -> str:
    """httpx sends header values as ASCII (an umlaut raised before 0.7.0 and the push was lost); ntfy reads RFC 2047
    for everything else."""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        import base64

        return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


class PushError(Exception):
    pass


class PushGone(PushError):
    """The device is no longer signed up (uninstalled, permission taken back); trying again will not help."""


#: How loud the push service should treat a message (RFC 8030); "high" may wake a sleeping phone.
URGENCY = {CRIT: "high", WARN: "normal"}


async def _send_webpush(
    config: dict[str, Any], title: str, body: str, priority: str, kind: str, thread_id: int | None, icon: str = ""
) -> None:
    with SessionLocal() as db:
        if not settings_service.get(db, "webpush_enabled"):
            raise PushError("web push is switched off under Rules, Forwarding to the phone")
        key = webpush.server_key(db)
        subject = webpush.subject(db)
    endpoint = str(config.get("url", ""))
    url = f"/?thread={thread_id}" if thread_id else "/"
    tag = f"thread-{thread_id}" if thread_id else ""
    data = webpush.payload(title, body or ("Resolved" if kind == "allclear" else ""), priority, url, tag, icon)
    content = webpush.encrypt(data, str(config.get("p256dh", "")), str(config.get("auth", "")))
    headers = {
        "Authorization": webpush.vapid_header(key, endpoint, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(webpush.TTL_SECONDS),
        "Urgency": URGENCY.get(priority, "low") if kind != "allclear" else "low",
    }
    async with _client() as client:
        try:
            response = await client.post(endpoint, content=content, headers=headers)
        except httpx.TimeoutException as error:
            raise PushError("no answer within 10 seconds") from error
        except httpx.HTTPError as error:
            raise PushError(f"not reachable ({type(error).__name__})") from error
    if response.status_code in (404, 410):
        raise PushGone("this device is no longer signed up; sign it up again")
    if response.status_code >= 400:
        raise PushError(f"the push service answered HTTP {response.status_code}")


async def deliver_due() -> int:
    """Sends everything that is due. Each delivery is its own short transaction."""
    now = utcnow()
    with SessionLocal() as db:
        due = [
            row.id
            for row in db.scalars(
                select(Delivery)
                .where(Delivery.status == "pending", Delivery.next_try_at <= now)
                .order_by(Delivery.id)
                .limit(50)
            )
        ]
    sent = 0
    for delivery_id in due:
        with SessionLocal() as db:
            delivery = db.get(Delivery, delivery_id)
            target = db.get(Target, delivery.target_id) if delivery else None
            if delivery is None or target is None:
                continue
            try:
                await send(
                    target,
                    delivery.title,
                    delivery.body,
                    delivery.priority,
                    delivery.link,
                    delivery.kind,
                    delivery.thread_id,
                    delivery.icon,
                )
            except PushGone as error:
                # Nothing to try again: the device left. The target goes off and says why.
                delivery.attempts += 1
                delivery.status = "failed"
                delivery.last_error = str(error)[:300]
                target.last_error = str(error)[:200]
                target.enabled = False
                logger.warning("Push to %s: %s", target.name, error)
            except PushError as error:
                delivery.attempts += 1
                delivery.last_error = str(error)[:300]
                target.last_error = f"{str(error)[:200]}"
                if delivery.attempts > len(RETRY_SECONDS):
                    delivery.status = "failed"
                    logger.warning("Push to %s given up after %s attempts: %s", target.name, delivery.attempts, error)
                else:
                    delivery.next_try_at = utcnow() + timedelta(seconds=RETRY_SECONDS[delivery.attempts - 1])
                    logger.info(
                        "Push to %s failed (%s), next try in %ss",
                        target.name,
                        error,
                        RETRY_SECONDS[delivery.attempts - 1],
                    )
            else:
                delivery.status = "sent"
                delivery.sent_at = utcnow()
                delivery.attempts += 1
                target.last_ok_at = utcnow()
                target.last_error = ""
                sent += 1
                logger.debug(
                    "Push sent to %s target_kind=%s kind=%s attempt=%s",
                    target.name,
                    target.kind,
                    delivery.kind,
                    delivery.attempts,
                )
            db.commit()
            if delivery.thread_id:
                bus.publish("thread", id=delivery.thread_id)
            bus.publish("target", id=target.id)
    return sent


async def run_forever(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                due_windows(db)
            await deliver_due()
        except Exception:
            logger.exception("Push worker round failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            continue
