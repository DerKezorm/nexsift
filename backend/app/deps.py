"""Who may do what.

Every request under ``/api`` except setup, sign-in, OIDC, health and the entrances for senders needs the session
cookie. Changing requests need the header ``X-Requested-By: nexsift`` on top: a foreign page cannot set it
without a preflight the browser refuses.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .meldungen import fehler
from .models import Account
from .security import CSRF_HEADER, CSRF_VALUE, SESSION_COOKIE, session_account
from .services import logs

DbSession = Annotated[Session, Depends(get_db)]
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@lru_cache(maxsize=4)
def _trusted_networks(spec: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks = []
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_proxy(address: str) -> bool:
    networks = _trusted_networks(get_settings().trusted_proxies)
    if not networks:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in networks)


def client_ip(request: Request) -> str:
    """The sender's address. ``X-Forwarded-For`` counts only behind a configured trusted proxy, and then the
    rightmost hop that is not itself one: everything left of it was written by the sender."""
    peer = (request.client.host if request.client else "-")[:64]
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded or not _is_trusted_proxy(peer):
        return peer
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _is_trusted_proxy(hop):
            return hop[:64]
    return (hops[0] if hops else peer)[:64]


def check_csrf(request: Request) -> None:
    if request.method in UNSAFE and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise fehler("missing_header", f"This request needs the header X-Requested-By: {CSRF_VALUE}.", 403)


def current_account(request: Request, db: DbSession) -> Account:
    check_csrf(request)
    account = session_account(db, request.cookies.get(SESSION_COOKIE))
    if account is None:
        raise fehler("not_signed_in", "Not signed in.", 401)
    logs.set_actor(account.name)
    return account


CurrentAccount = Annotated[Account, Depends(current_account)]
