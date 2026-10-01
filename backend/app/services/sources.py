"""Sources: creating them with their token or key, finding them again when a message comes in, and what the
operator has to enter in the sender."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..config import get_settings
from ..models import Source, utcnow
from . import presets, settings_service

TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
HOSTNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
#: A topic or mail name the operator picks (usually one a device already uses, from the list of strangers).
OWN_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class SourceError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _token(length: int = 24) -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


def _token_for(protocol: str) -> str:
    """A token in the shape the sender expects. Gotify app tokens are 15 characters starting with "A", and
    shoutrrr (inside Watchtower and many others) refuses anything else before it sends: "invalid gotify token".
    Found with a real Watchtower on 01.10.2026. 14 random characters are still about 81 bits."""
    if protocol == "gotify":
        return "A" + _token(14)
    return _token()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def slug(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return cleaned[:40] or "source"


def create(db: Session, preset: str, name: str, hostname: str = "", key: str = "") -> Source:
    """``hostname`` is required for syslog. ``key`` optionally picks the ntfy topic or the mail name instead of a
    generated one; that is how a sender that already knocks with its own topic gets its source in one click."""
    if preset not in presets.PRESETS:
        raise SourceError("unknown_preset", "Unknown kind of source.")
    info = presets.PRESETS[preset]
    name = " ".join(name.split())[:80] or info["name"]
    source = Source(name=name, kind=info["kind"], protocol=info["protocol"])
    protocol = info["protocol"]
    if protocol in ("gotify", "webhook", "discord"):
        token = _token_for(protocol)
        source.token_hash = hash_token(token)
        source.token_enc = crypto.encrypt_secret(token)
    if protocol == "discord":
        # Discord's webhook address has a number and a token; the number only has to look like one.
        source.match_key = f"discord:{secrets.randbelow(9 * 10**17) + 10**17}"
    elif protocol in ("ntfy", "smtp") and key.strip():
        own = key.strip().lower()
        if not OWN_KEY.match(own):
            raise SourceError("key_invalid", "Use letters, digits, dots, dashes or underscores.")
        if db.scalar(select(Source).where(Source.match_key == f"{protocol}:{own}")) is not None:
            raise SourceError("key_taken", "Another source already uses this.", 409)
        source.match_key = f"{protocol}:{own}"
    elif protocol == "ntfy":
        source.match_key = f"ntfy:{slug(name)}-{_token(6).lower()}"
    elif protocol == "smtp":
        base = slug(name)
        candidate, suffix = base, 1
        while db.scalar(select(Source).where(Source.match_key == f"smtp:{candidate}")) is not None:
            suffix += 1
            candidate = f"{base}-{suffix}"
        source.match_key = f"smtp:{candidate}"
    elif protocol == "syslog":
        host = hostname.strip().lower()
        if not HOSTNAME.match(host):
            raise SourceError("hostname_required", "Enter the host name (or address) the device sends syslog as.")
        if db.scalar(select(Source).where(Source.match_key == f"syslog:{host}")) is not None:
            raise SourceError("hostname_taken", "There is already a source for this host name.", 409)
        source.match_key = f"syslog:{host}"
    db.add(source)
    db.commit()
    presets.install_source_rules(db, preset, source.id)
    return source


def renew_token(db: Session, source: Source) -> None:
    if source.protocol not in ("gotify", "webhook", "discord"):
        raise SourceError("no_token", "This source has no token.")
    token = _token_for(source.protocol)
    source.token_hash = hash_token(token)
    source.token_enc = crypto.encrypt_secret(token)
    db.commit()


def by_token(db: Session, token: str, protocol: str) -> Source | None:
    if not token or len(token) > 200:
        return None
    source = db.scalar(select(Source).where(Source.token_hash == hash_token(token)))
    return source if source is not None and source.protocol == protocol else None


def by_key(db: Session, key: str) -> Source | None:
    return db.scalar(select(Source).where(Source.match_key == key))


def is_muted(source: Source) -> bool:
    return source.muted_until is not None and source.muted_until > utcnow()


def _host(db: Session, request_host: str) -> tuple[str, str, str]:
    """Scheme and host the senders should use, and where they came from: the sender address set for the devices
    at home, else the public address, else the request."""
    sender = settings_service.get(db, "sender_host")
    if sender:
        return "http", sender, "sender"
    public = settings_service.public_url(db)
    if public:
        parts = urlsplit(public)
        return parts.scheme, parts.hostname or request_host, "public"
    return "http", request_host.split(":", 1)[0] or "localhost", "request"


#: How long a name's resolution is trusted, in seconds. Short: the operator fixes DNS and looks again.
_RESOLVE_SECONDS = 60
_resolved: dict[str, tuple[float, str]] = {}


def outside_address(host: str) -> str:
    """The internet address a host name leads to, or empty when it leads home (or nowhere).

    A name like nexsift.example.com often points at the router's public address even inside the house; the
    router only forwards the reverse proxy's port, so syslog, SMTP and the doors on their own ports never reach
    nexsift that way (seen on a Synology, 01.10.2026). The setup dialog warns when this is the case."""
    try:
        return "" if not ipaddress.ip_address(host.strip("[]")).is_global else host
    except ValueError:
        pass
    if "." not in host or host.endswith((".local", ".lan", ".home.arpa", ".internal", ".fritz.box")):
        # A single label or a home suffix never leads out; and no lookup that could stall on it.
        return ""
    now = time.monotonic()
    cached = _resolved.get(host)
    if cached and now - cached[0] < _RESOLVE_SECONDS:
        return cached[1]
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)}
    except OSError:
        addresses = set()
    public = sorted(address for address in addresses if ipaddress.ip_address(address.split("%", 1)[0]).is_global)
    result = public[0] if addresses and len(public) == len(addresses) else ""
    _resolved[host] = (now, result)
    return result


def connection(db: Session, source: Source, request_host: str) -> dict[str, Any]:
    """Everything the setup hint needs, already put together. The interface only arranges it into sentences."""
    scheme, host, origin = _host(db, request_host)
    ports = get_settings().outside_ports()
    public = settings_service.public_url(db)
    shown = f"[{host}]" if ":" in host else host
    web = f"http://{shown}:{ports['web']}" if origin == "sender" else (public or f"{scheme}://{shown}:{ports['web']}")
    host = shown
    token = crypto.decrypt_secret(source.token_enc) if source.token_enc else ""
    key = (source.match_key or "").split(":", 1)[-1]
    info: dict[str, Any] = {
        "host": host,
        "host_from": origin,
        "host_outside": outside_address(host.strip("[]")),
        "ports": ports,
        "token": token,
    }
    if source.protocol == "gotify":
        info["server"] = f"http://{host}:{ports['gotify']}"
        info["shoutrrr"] = f"gotify://{host}:{ports['gotify']}/{token}?disabletls=yes"
    elif source.protocol == "ntfy":
        info["server"] = f"http://{host}:{ports['ntfy']}"
        info["topic"] = key
        info["url"] = f"http://{host}:{ports['ntfy']}/{key}"
    elif source.protocol == "webhook":
        info["url"] = f"{web}/api/v1/hook/{token}"
    elif source.protocol == "discord":
        info["url"] = f"{web}/api/webhooks/{key}/{token}"
    elif source.protocol == "smtp":
        info["server"] = host
        info["port"] = ports["smtp"]
        info["recipient"] = f"{key}@nexsift.local"
    elif source.protocol == "syslog":
        info["server"] = host
        info["port"] = ports["syslog"]
        info["hostname"] = key
    return info


def view(db: Session, source: Source) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "kind": source.kind,
        "protocol": source.protocol,
        "created_at": source.created_at.isoformat(),
        "last_seen_at": source.last_seen_at.isoformat() if source.last_seen_at else None,
        "count_total": source.count_total,
        "muted_until": source.muted_until.isoformat() if is_muted(source) and source.muted_until else None,
        "unrecognized_streak": source.unrecognized_streak,
        "last_unrecognized_at": source.last_unrecognized_at.isoformat() if source.last_unrecognized_at else None,
    }
