"""What nexsift knows about particular senders, on top of the door they use.

Each function takes the ``Incoming`` the door made and the parsed payload, and returns one or more events. When
a sender's format is not what the function expects, it returns the door's event unchanged with
``recognized=False``: the message arrives, only the extra understanding is missing.

Every format here is pinned by real samples in ``tests/samples``; when a sender changes its wording, a new
sample goes next to the old one and the function learns both.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ..models import CRIT, INFO, WARN
from .base import Incoming, links_from_text, word_priority

Payload = dict[str, Any]
Refiner = Callable[[Incoming, Payload], list[Incoming]]


def _unrecognized(incoming: Incoming) -> list[Incoming]:
    incoming.recognized = False
    return [incoming]


# --- Uptime Kuma --------------------------------------------------------------------------------------------- #
#
# Webhook, body "application/json": {"heartbeat": {"status": 0|1|2|3, "msg": …}, "monitor": {"id", "name", "url"},
# "msg": "[name] [🔴 Down] …"}. The status number decides, not the sentence. The test button sends only "msg".

KUMA_DOWN, KUMA_UP, KUMA_PENDING, KUMA_MAINTENANCE = 0, 1, 2, 3


def uptimekuma(incoming: Incoming, payload: Payload) -> list[Incoming]:
    monitor = payload.get("monitor") if isinstance(payload.get("monitor"), dict) else None
    heartbeat = payload.get("heartbeat") if isinstance(payload.get("heartbeat"), dict) else None
    if monitor is None or heartbeat is None:
        message = str(payload.get("msg", "") or "")
        if message and not monitor and not heartbeat:
            # The test button of Uptime Kuma: a plain line. Understood, nothing to group.
            return [Incoming(title=message, priority=INFO, raw=incoming.raw)]
        return _unrecognized(incoming)
    name = str(monitor.get("name") or monitor.get("id") or "monitor")
    key = f"monitor-{monitor.get('id', name)}"
    status = heartbeat.get("status")
    detail = str(heartbeat.get("msg", "") or "")
    url = str(monitor.get("url") or "")
    links = [{"label": url.split("://", 1)[-1].split("/", 1)[0], "url": url}] if url.startswith("http") else []
    fields = {"monitor": name}
    if status == KUMA_DOWN:
        return [
            Incoming(
                title=f"{name} is down",
                body=detail,
                priority=CRIT,
                links=links,
                raw=incoming.raw,
                fields=fields,
                group_key=key,
            )
        ]
    if status == KUMA_UP:
        return [
            Incoming(
                title=f"{name} is up again",
                body=detail,
                priority=INFO,
                links=links,
                raw=incoming.raw,
                fields=fields,
                resolves=key,
                group_key=key,
            )
        ]
    if status == KUMA_PENDING:
        return [
            Incoming(
                title=f"{name} is not answering yet",
                body=detail,
                priority=WARN,
                links=links,
                raw=incoming.raw,
                fields=fields,
                group_key=key,
            )
        ]
    if status == KUMA_MAINTENANCE:
        return [
            Incoming(
                title=f"{name} is in maintenance",
                body=detail,
                priority=INFO,
                links=links,
                raw=incoming.raw,
                fields=fields,
                group_key=key,
            )
        ]
    return _unrecognized(incoming)


# --- Proxmox VE ---------------------------------------------------------------------------------------------- #
#
# Webhook target with the body nexsift hands out: {"title", "message", "severity", "type", "host"}. Severity is
# Proxmox's own word (info, notice, warning, error, unknown). Group by what happened on which host.


def proxmox(incoming: Incoming, payload: Payload) -> list[Incoming]:
    if "severity" not in payload and "title" not in payload:
        return _unrecognized(incoming)
    priority = word_priority(payload.get("severity")) or incoming.priority
    kind = str(payload.get("type", "") or "").strip()
    host = str(payload.get("host", "") or payload.get("hostname", "") or "").strip()
    incoming.priority = priority
    incoming.fields = {key: value for key, value in (("type", kind), ("host", host)) if value}
    if kind:
        incoming.group_key = f"{kind}-{host}" if host else kind
        # A job of the same kind on the same host that went well is the all-clear for one that failed: a good
        # backup after a failed one closes the red line instead of joining it (seen for real on 30.09.2026).
        # Without an open problem it simply becomes a line of its own.
        if priority == INFO:
            incoming.resolves = incoming.group_key
    return [incoming]


# --- Watchtower ---------------------------------------------------------------------------------------------- #
#
# Through shoutrrr's Gotify service: title "Watchtower updates on <host>", the message is a list of log lines.
# Two shapes exist: the classic log lines ("Found new nginx:latest image (…)") and the session report
# ("- nginx (nginx:latest): abc updated to def"). Each updated container becomes its own event, so the bundle
# counts containers, not messages; failures come out as warnings.

WT_FOUND = re.compile(r"Found new (?P<image>\S+?)(?::\S+)? image \(", re.IGNORECASE)
WT_REPORT = re.compile(
    r"^\s*-\s*(?P<name>[^\s(]+)\s*\((?P<image>[^)]+)\):\s*\S+\s+updated to\s+\S+", re.IGNORECASE | re.MULTILINE
)
# "0 Failed" in the session report is the good news, not a failure.
WT_FAILED = re.compile(r"(level=error|(?<!0 )\bfailed\b|could not|unable to)", re.IGNORECASE)


def watchtower(incoming: Incoming, payload: Payload) -> list[Incoming]:
    text = f"{incoming.title}\n{incoming.body}"
    host = ""
    host_match = re.search(r"Watchtower updates on (\S+)", text)
    if host_match:
        host = host_match.group(1)
    names = [m.group("name") for m in WT_REPORT.finditer(text)] or [
        m.group("image").rsplit("/", 1)[-1] for m in WT_FOUND.finditer(text)
    ]
    failures = [line.strip() for line in text.splitlines() if WT_FAILED.search(line)]
    events: list[Incoming] = []
    for name in dict.fromkeys(names):
        events.append(
            Incoming(
                title=f"Updated {name}",
                body=f"Watchtower updated {name}" + (f" on {host}." if host else "."),
                priority=INFO,
                raw=incoming.raw,
                fields={"container": name, "host": host},
                group_key="updates",
            )
        )
    for line in failures[:10]:
        events.append(
            Incoming(
                title=f"Watchtower: {line[:200]}",
                priority=WARN,
                raw=incoming.raw,
                fields={"host": host},
                group_key="failures",
            )
        )
    if not events:
        # A startup notice ("Watchtower 1.7.1 … Scheduling first run") or a format we do not know.
        if "watchtower" in text.lower():
            return [
                Incoming(title=incoming.title, body=incoming.body, priority=INFO, raw=incoming.raw, group_key="notices")
            ]
        return _unrecognized(incoming)
    return events


# --- Synology, UPS and other mail senders -------------------------------------------------------------------- #
#
# The subject carries everything. A leading "[host]" is taken as the host; numbers are left out of the group key
# so "Volume 1 is 90 % full" and "… 91 % full" land in one thread.


SUBJECT_HOST = re.compile(r"^\s*\[([^\]]{1,64})\]\s*")


def mail(incoming: Incoming, payload: Payload) -> list[Incoming]:
    subject = str(payload.get("subject", "") or incoming.title)
    match = SUBJECT_HOST.match(subject)
    if match:
        incoming.fields["host"] = match.group(1)
        incoming.title = subject[match.end() :] or subject
    return [incoming]


# --- Syslog ------------------------------------------------------------------------------------------------- #


def syslog(incoming: Incoming, payload: Payload) -> list[Incoming]:
    app = str(payload.get("app", "") or "")
    if app:
        incoming.group_key = f"{app}:{shape(incoming.title)}"
    return [incoming]


# --- Paperless-ngx ------------------------------------------------------------------------------------------- #


def paperless(incoming: Incoming, payload: Payload) -> list[Incoming]:
    incoming.links = [
        {"label": "Open in Paperless", "url": link["url"]} for link in incoming.links[:1]
    ] + incoming.links[1:]
    incoming.group_key = "documents"
    return [incoming]


def generic(incoming: Incoming, payload: Payload) -> list[Incoming]:
    return [incoming]


REFINERS: dict[str, Refiner] = {
    "uptimekuma": uptimekuma,
    "proxmox": proxmox,
    "watchtower": watchtower,
    "synology": mail,
    "ups": mail,
    "email": mail,
    "syslog": syslog,
    "paperless": paperless,
}


def refine(kind: str, incoming: Incoming, payload: Payload) -> list[Incoming]:
    events = REFINERS.get(kind, generic)(incoming, payload)
    for event in events:
        if not event.links:
            event.links = links_from_text(event.body)
        event.clean()
    return events


NUMBER = re.compile(r"\d+([.,:]\d+)*")
HEX = re.compile(r"\b[0-9a-f]{7,}\b", re.IGNORECASE)
ADDRESS = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")


def shape(text: str) -> str:
    """The form of a message without its numbers, ids and addresses: what makes "the same message" the same.
    ``sshd: Failed password for invalid user admin from 203.0.113.4 port 51122`` and the same line with another
    port and address have one shape."""
    text = ADDRESS.sub("#", text.lower())
    text = HEX.sub("#", text)
    text = NUMBER.sub("#", text)
    return " ".join(text.split())[:160]
