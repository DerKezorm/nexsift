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
WT_CREATED = re.compile(r"^Creating /(\S+)", re.MULTILINE)
# The first lines of a Watchtower start: "Watchtower 1.7.1", "Using notifications: gotify", "Scheduling first run".
WT_STARTED = re.compile(r"^Watchtower v?\d+\.\d+", re.MULTILINE)
# "0 Failed" in the session report is the good news, not a failure.
WT_FAILED = re.compile(r"(level=error|(?<!0 )\bfailed\b|could not|unable to)", re.IGNORECASE)


def watchtower(incoming: Incoming, payload: Payload) -> list[Incoming]:
    text = f"{incoming.title}\n{incoming.body}"
    host = ""
    host_match = re.search(r"Watchtower updates on (\S+)", text)
    if host_match:
        host = host_match.group(1)
    # Container names, as the operator knows them, without the leading slash Docker puts there. The session
    # report names containers; the log lines name images, but "Creating /name" follows every real update.
    # Only without those (monitor-only) the image has to do.
    names = (
        [m.group("name").lstrip("/") for m in WT_REPORT.finditer(text)]
        or [m.group(1) for m in WT_CREATED.finditer(text)]
        or [m.group("image").rsplit("/", 1)[-1] for m in WT_FOUND.finditer(text)]
    )
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
        # The startup notice comes under the same title as updates ("Watchtower updates on <host>") although it
        # holds none; named for what it is, found with a real Watchtower on 01.10.2026.
        if WT_STARTED.search(incoming.body):
            return [
                Incoming(
                    title="Watchtower started" + (f" on {host}" if host else ""),
                    body=incoming.body,
                    priority=INFO,
                    raw=incoming.raw,
                    group_key="started",
                )
            ]
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
    """Nothing to add: routine lines join the source's routine, the rest groups by its shape like any sender."""
    return [incoming]


# --- Paperless-ngx ------------------------------------------------------------------------------------------- #


def paperless(incoming: Incoming, payload: Payload) -> list[Incoming]:
    incoming.links = [
        {"label": "Open in Paperless", "url": link["url"]} for link in incoming.links[:1]
    ] + incoming.links[1:]
    incoming.group_key = "documents"
    return [incoming]


# --- Uptime Kuma through its Discord notification ------------------------------------------------------------ #
#
# Kuma's Discord message: username "Uptime Kuma", one embed titled "❌ Your service <name> went down. ❌" or
# "✅ Your service <name> is up! ✅", with fields "Service Name", "Service URL", "Error" or "Ping". Recorded from
# a real Uptime Kuma 1.23 on 01.10.2026.

KUMA_DISCORD_TITLE = re.compile(r"Your service (?P<name>.+?) (?P<state>went down|is up)", re.IGNORECASE)


def kuma_discord(incoming: Incoming, payload: Payload) -> list[Incoming] | None:
    embeds = payload.get("embeds") if isinstance(payload.get("embeds"), list) else []
    if "kuma" not in str(payload.get("username", "")).lower() or not embeds or not isinstance(embeds[0], dict):
        return None
    match = KUMA_DISCORD_TITLE.search(str(embeds[0].get("title", "")))
    if not match:
        return None
    fields = {
        str(item.get("name")): str(item.get("value", ""))
        for item in embeds[0].get("fields") or []
        if isinstance(item, dict)
    }
    name = fields.get("Service Name") or match.group("name")
    key = f"monitor-{name}"
    links = [{"label": "", "url": fields["Service URL"]}] if fields.get("Service URL", "").startswith("http") else []
    if match.group("state").lower() == "went down":
        detail = fields.get("Error", "")
        return [
            Incoming(
                title=f"{name} is down",
                body=detail,
                priority=CRIT,
                links=links,
                raw=incoming.raw,
                fields={"monitor": name},
                group_key=key,
            )
        ]
    detail = f"Ping {fields['Ping']}" if fields.get("Ping") else ""
    return [
        Incoming(
            title=f"{name} is up again",
            body=detail,
            priority=INFO,
            links=links,
            raw=incoming.raw,
            fields={"monitor": name},
            resolves=key,
            group_key=key,
        )
    ]


def generic(incoming: Incoming, payload: Payload) -> list[Incoming]:
    """A source of the general kind still recognizes formats nexsift knows by their shape: Uptime Kuma pointed at
    a plain webhook or a Discord door pairs its outages and recoveries all the same."""
    if isinstance(payload.get("heartbeat"), dict) and isinstance(payload.get("monitor"), dict):
        return uptimekuma(incoming, payload)
    understood = kuma_discord(incoming, payload)
    return understood if understood is not None else [incoming]


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
