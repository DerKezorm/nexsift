"""The doors: what each protocol looks like on the wire, turned into an ``Incoming`` plus the parsed payload.

These formats are the published APIs of Gotify, ntfy and Discord, and nexsift's own webhook. They do not change
under a sender's feet: a sender that broke them would break against the real service too.
"""

from __future__ import annotations

import json
import re
from email.message import EmailMessage
from typing import Any

from ..models import CRIT, INFO, WARN
from .base import Incoming, gotify_priority, links_from_text, ntfy_priority, safe_url, word_priority

Payload = dict[str, Any]


def _as_json(body: bytes) -> Any:
    # strict=False: real line breaks inside JSON strings are read, not refused. Templates without escaping
    # (Proxmox examples, own scripts) produce exactly that, and refusing would lose the whole structure.
    try:
        return json.loads(body.decode("utf-8", errors="replace"), strict=False)
    except ValueError:
        return None


def _text(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def gotify(body: bytes, form: dict[str, str], content_type: str) -> tuple[Incoming, Payload]:
    """``POST /message``: JSON or form with title, message, priority; a click URL may sit in the extras."""
    data = _as_json(body) if "json" in content_type or body[:1] in (b"{", b"[") else None
    payload: Payload = data if isinstance(data, dict) else dict(form)
    message = str(payload.get("message", "") or "")
    title = str(payload.get("title", "") or "") or message.split("\n", 1)[0]
    links = []
    extras = payload.get("extras") if isinstance(payload.get("extras"), dict) else {}
    click = ((extras.get("client::notification") or {}).get("click") or {}).get("url") if extras else None
    if isinstance(click, str) and safe_url(click):
        links.append({"label": "", "url": click})
    links += links_from_text(message)
    incoming = Incoming(
        title=title,
        body=message if message != title else "",
        priority=gotify_priority(payload.get("priority", 0)),
        links=links,
        raw=_text(body) if data is not None else json.dumps(payload, ensure_ascii=False),
    )
    return incoming, payload


def ntfy(body: bytes, headers: dict[str, str], query: dict[str, str], content_type: str) -> tuple[Incoming, Payload]:
    """``POST /<topic>`` with the message as body and title, priority, tags, click in headers or query; or JSON to
    the root with a ``topic`` field. Both forms are ntfy's own."""

    def pick(*names: str) -> str:
        for name in names:
            value = headers.get(name.lower()) or query.get(name.lower())
            if value:
                return value
        return ""

    data = _as_json(body) if body[:1] == b"{" else None
    if isinstance(data, dict) and ("topic" in data or "message" in data):
        payload: Payload = data
        message = str(data.get("message", "") or "")
        title = str(data.get("title", "") or "")
        priority = ntfy_priority(data.get("priority", 3))
        click = str(data.get("click", "") or "")
        tags = data.get("tags") or []
    else:
        message = _text(body)
        title = pick("X-Title", "Title", "t")
        priority = ntfy_priority(pick("X-Priority", "Priority", "prio", "p") or 3)
        click = pick("X-Click", "Click")
        tags = [tag.strip() for tag in pick("X-Tags", "Tags", "ta").split(",") if tag.strip()]
        payload = {"message": message, "title": title, "priority": priority, "click": click, "tags": tags}
    # ntfy clients send tags like "warning" or "rotating_light"; one of those lifts an unspecified priority.
    tag_words = {str(tag).lower() for tag in tags} if isinstance(tags, list) else set()
    if priority == INFO and tag_words & {"rotating_light", "skull", "x", "no_entry", "sos"}:
        priority = CRIT
    elif priority == INFO and tag_words & {"warning", "exclamation"}:
        priority = WARN
    links = [{"label": "", "url": click}] if click and safe_url(click) else []
    links += links_from_text(message)
    first_line = message.strip().split("\n", 1)[0]
    incoming = Incoming(
        title=title or first_line,
        body=message if title else message.strip()[len(first_line) :].strip(),
        priority=priority,
        links=links,
        raw=_text(body)
        if data is not None
        else json.dumps({"headers": _visible(headers), "body": message}, ensure_ascii=False),
    )
    return incoming, payload


def _visible(headers: dict[str, str]) -> dict[str, str]:
    """Headers worth keeping in the raw data: ntfy's own, never cookies or authorization."""
    return {
        key: value
        for key, value in headers.items()
        if key.startswith("x-") or key in ("title", "priority", "tags", "click")
    }


DISCORD_COLORS = {15548997: CRIT, 16711680: CRIT, 15158332: CRIT, 16776960: WARN, 15105570: WARN, 16753920: WARN}


def discord(body: bytes) -> tuple[Incoming, Payload]:
    """A Discord webhook call: ``content`` and/or ``embeds``. The embed color is the only hint of urgency
    Discord has; red and orange shades count."""
    data = _as_json(body)
    payload: Payload = data if isinstance(data, dict) else {"content": _text(body)}
    content = str(payload.get("content", "") or "")
    embeds = payload.get("embeds") if isinstance(payload.get("embeds"), list) else []
    title, parts, links, priority = "", [], [], INFO
    for embed in embeds[:5]:
        if not isinstance(embed, dict):
            continue
        title = title or str(embed.get("title", "") or "")
        if embed.get("description"):
            parts.append(str(embed["description"]))
        for item in (embed.get("fields") or [])[:20]:
            if isinstance(item, dict) and item.get("name"):
                parts.append(f"{item.get('name')}: {item.get('value', '')}")
        url = embed.get("url")
        if isinstance(url, str) and safe_url(url):
            links.append({"label": "", "url": url})
        color = embed.get("color")
        if isinstance(color, int) and color in DISCORD_COLORS:
            priority = DISCORD_COLORS[color] if priority == INFO else priority
    body_text = "\n".join(parts)
    if not title:
        title = content.split("\n", 1)[0] or body_text.split("\n", 1)[0]
        content = content[len(title) :].strip() if content.startswith(title) else content
    incoming = Incoming(
        title=title,
        body="\n".join(part for part in (content, body_text) if part),
        priority=priority,
        links=links + links_from_text(content, body_text),
        raw=_text(body),
    )
    return incoming, payload


def webhook(body: bytes, content_type: str) -> tuple[Incoming, Payload]:
    """nexsift's own webhook: JSON with title, message and priority, all optional. Anything else is taken as
    text. The field names of the usual suspects (text, body, content, severity, level, status) work too, so a
    sender with fixed JSON can often be pointed here unchanged."""
    data = _as_json(body)
    if isinstance(data, str) and data.lstrip().startswith("{"):
        # JSON written into a JSON string: what Paperless sends when its body is a template and "send as JSON"
        # is on anyway. Read the inner object instead of showing the quoted text.
        data = _as_json(data.encode("utf-8"))
    if not isinstance(data, dict) and "x-www-form-urlencoded" in content_type.lower():
        # DSM's custom webhook sends a form unless JSON is chosen: text=<message>. Read as the same fields.
        from urllib.parse import parse_qsl

        form = dict(parse_qsl(_text(body), keep_blank_values=True))
        data = form or None
    if not isinstance(data, dict):
        text = _text(body).strip()
        first = text.split("\n", 1)[0]
        return Incoming(title=first, body=text[len(first) :].strip(), raw=text, links=links_from_text(text)), {
            "text": text
        }
    payload: Payload = data

    def first(*names: str) -> str:
        for name in names:
            value = data.get(name)
            if isinstance(value, str | int | float) and str(value).strip():
                return str(value)
        return ""

    message = first("message", "text", "body", "content", "description", "msg")
    title = first("title", "subject", "summary", "name") or message.split("\n", 1)[0]
    priority_value = first("priority", "severity", "level", "status")
    priority = word_priority(priority_value)
    if priority is None:
        priority = gotify_priority(priority_value) if priority_value.isdigit() else INFO
    links = []
    raw_links = data.get("links")
    if isinstance(raw_links, list):
        for item in raw_links[:5]:
            if isinstance(item, dict) and safe_url(str(item.get("url", ""))):
                links.append({"label": str(item.get("label", ""))[:60], "url": str(item["url"])})
    url = first("url", "link", "click")
    if url and safe_url(url):
        links.append({"label": "", "url": url})
    links += links_from_text(message)
    incoming = Incoming(
        title=title,
        body=message if message != title else "",
        priority=priority,
        links=links,
        raw=_text(body),
    )
    return incoming, payload


def email(message: EmailMessage, raw: bytes) -> tuple[Incoming, Payload]:
    """A mail: subject becomes the title, the plain text the body. HTML-only mails lose their markup."""
    subject = " ".join(str(message.get("subject", "") or "").split())
    part = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if part is not None:
        try:
            text = part.get_content()
        except (LookupError, UnicodeDecodeError):
            text = ""
        if part.get_content_type() == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    priority = INFO
    importance = f"{message.get('importance', '')} {message.get('x-priority', '')}".lower()
    if "high" in importance or importance.strip().startswith("1"):
        priority = WARN
    payload = {"subject": subject, "from": str(message.get("from", "")), "to": str(message.get("to", ""))}
    incoming = Incoming(
        title=subject or text.split("\n", 1)[0],
        body=text,
        priority=priority,
        links=links_from_text(text),
        raw=raw.decode("utf-8", errors="replace"),
    )
    return incoming, payload


SYSLOG_5424 = re.compile(r"^<(\d{1,3})>1 (\S+) (\S+) (\S+) (\S+) (\S+) (?:-|\[.*?\])\s?(.*)$", re.DOTALL)
SYSLOG_3164 = re.compile(
    r"^<(\d{1,3})>([A-Z][a-z]{2}\s+\d{1,2} \d{2}:\d{2}:\d{2}) (\S+) ([^:\[\s]+)(?:\[\d+\])?:\s?(.*)$", re.DOTALL
)
SYSLOG_PRI = re.compile(r"^<(\d{1,3})>(.*)$", re.DOTALL)


def syslog_severity(pri: int) -> str:
    severity = pri % 8
    if severity <= 3:
        return CRIT
    if severity == 4:
        return WARN
    return INFO


def syslog(line: str, peer: str) -> tuple[Incoming, Payload]:
    """RFC 5424, RFC 3164, or just ``<pri>text``. The hostname identifies the source; without one, the sender's
    address does."""
    line = line.strip()
    host, app, message, pri = peer, "", line, 13
    match = SYSLOG_5424.match(line)
    if match:
        pri, host, app, message = int(match.group(1)), match.group(3), match.group(4), match.group(7)
    else:
        match = SYSLOG_3164.match(line)
        if match:
            pri, host, app, message = int(match.group(1)), match.group(3), match.group(4), match.group(5)
        else:
            match = SYSLOG_PRI.match(line)
            if match:
                pri, message = int(match.group(1)), match.group(2)
    if host in ("-", ""):
        host = peer
    if app == "-":
        app = ""
    message = message.strip()
    payload = {"host": host, "app": app, "pri": pri}
    incoming = Incoming(
        title=f"{app}: {message}" if app else message,
        body="",
        priority=syslog_severity(pri),
        raw=line,
        fields={"host": host, "app": app},
    )
    return incoming, payload
