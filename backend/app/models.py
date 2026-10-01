"""The data model.

* ``Source``: who reports, and through which door. The token is stored twice: as a hash to find the source
  fast on every incoming message, and encrypted so the setup hint can show it again (a token only allows
  posting messages, and "show me the line again" is worth more than hiding it).
* ``Thread``: one line in the inbox. Events of the same source with the same group key land in the same thread
  while it is open; that is the bundling.
* ``Event``: one message as it came in, with what the sender really sent (``raw``) for "why does it look
  like this".
* ``Rule``: top to bottom, every matching one applies, per field the topmost wins.
* ``Target`` and ``Delivery``: where important things go, and every attempt to get them there.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """SQLite forgets the time zone. Stored as UTC, read back as UTC with the zone attached."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


INFO, WARN, CRIT = "info", "warn", "crit"
PRIORITIES = (INFO, WARN, CRIT)
#: The group key of the line that collects a source's routine: every info message nothing more specific claims.
#: Works for any sender without knowing it; warnings and critical ones stay apart, one line per subject.
ROUTINE_KEY = "__routine__"

RANK = {INFO: 0, WARN: 1, CRIT: 2}

UNREAD, READ, ARCHIVED = "unread", "read", "archived"
THREAD_STATES = (UNREAD, READ, ARCHIVED)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


class Account(Base):
    """nexsift has one account, the operator. The table keeps room for more without promising them."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text, default="")
    #: OIDC comes in when the provider vouches for this address (email_verified).
    email: Mapped[str] = mapped_column(String(255), default="")
    oidc_subject: Mapped[str] = mapped_column(String(255), default="")
    prefs: Mapped[Any] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    #: The preset it was created from (watchtower, proxmox, uptimekuma, …); decides the adapter.
    kind: Mapped[str] = mapped_column(String(32))
    #: The door: gotify, ntfy, discord, webhook, smtp, syslog.
    protocol: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    token_enc: Mapped[str] = mapped_column(Text, default="")
    #: What identifies the source when there is no token: ntfy topic, email recipient, syslog hostname.
    match_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    count_total: Mapped[int] = mapped_column(Integer, default=0)
    muted_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Messages in a row the adapter did not understand. Shown on the source, so a changed format is noticed.
    unrecognized_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_unrecognized_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (Index("ix_threads_open", "source_id", "group_key", "resolved_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    group_key: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    #: The bundle title with {count}, when a rule gave one.
    title_template: Mapped[str] = mapped_column(String(300), default="")
    priority: Mapped[str] = mapped_column(String(8), default=INFO)
    state: Mapped[str] = mapped_column(String(12), default=UNREAD, index=True)
    rule_names: Mapped[Any] = mapped_column(JSON, default=list)
    push_mode: Mapped[str] = mapped_column(String(12), default="")
    first_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    resolved_by: Mapped[str] = mapped_column(String(300), default="")
    #: Above the limit only counted, not stored.
    throttled_count: Mapped[int] = mapped_column(Integer, default=0)
    #: End of the bundle window: until then, more events of this kind join this thread quietly.
    window_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Events that came in after the last push; a follow-up is due for them at the end of the window.
    since_push: Mapped[int] = mapped_column(Integer, default=0)
    pushed: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Soft delete, so "undo" works; really removed a few minutes later.
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(8), default=INFO)
    links: Mapped[Any] = mapped_column(JSON, default=list)
    #: What the sender sent, cut to a sane length; emptied after the raw retention.
    raw: Mapped[str] = mapped_column(Text, default="")
    #: Whether the adapter understood the format. False: taken as plain title and text.
    recognized: Mapped[bool] = mapped_column(Boolean, default=True)


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=True)
    #: [{field: title|body|any, op: word|contains|regex, value}]
    conditions: Mapped[Any] = mapped_column(JSON, default=list)
    #: {priority, group_key, title_template, resolves, push, drop}
    actions: Mapped[Any] = mapped_column(JSON, default=dict)
    #: Set for rules nexsift created itself (with a source preset); they can be switched off but explain themselves.
    built_in: Mapped[str] = mapped_column(String(64), default="")


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(80))
    #: JSON with address, token, chat id …, encrypted as a whole.
    config_enc: Mapped[str] = mapped_column(Text, default="")
    min_priority: Mapped[str] = mapped_column(String(8), default=CRIT)
    #: "23:00" to "07:00" in the server's time zone; empty: no quiet hours.
    quiet_from: Mapped[str] = mapped_column(String(5), default="")
    quiet_to: Mapped[str] = mapped_column(String(5), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_ok_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="")


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    #: first, followup, allclear, storm, test
    kind: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(8), default=CRIT)
    link: Mapped[str] = mapped_column(Text, default="")
    #: pending, sent, failed
    status: Mapped[str] = mapped_column(String(8), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_try_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="")


class ApiKey(Base):
    """A read-only key for a dashboard (nexdeck and the like). Only the hash is kept; the key is shown once."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    #: The first characters, so the operator can tell keys apart without the key.
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
