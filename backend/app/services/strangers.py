"""Senders that knocked on a door no source answers: a mail to an unknown recipient, syslog from an unknown host,
an ntfy topic nobody set up.

Kept in memory (the last few) and shown on the sources page with a button that creates the matching source.
That turns the most common setup mistake, a typo or a device that names itself differently than expected, into
one click instead of a search. Nothing of the message itself is stored beyond a short sample.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime
from typing import Any

from ..models import utcnow
from . import bus

MAX = 20
SAMPLE = 200

_lock = threading.Lock()
_seen: OrderedDict[str, dict[str, Any]] = OrderedDict()


def knock(protocol: str, key: str, sample: str, peer: str = "") -> None:
    key = key.strip()[:128]
    if not key:
        return
    name = f"{protocol}:{key}"
    now: datetime = utcnow()
    with _lock:
        entry = _seen.pop(name, None) or {"protocol": protocol, "key": key, "count": 0, "first_at": now.isoformat()}
        entry["count"] += 1
        entry["last_at"] = now.isoformat()
        entry["sample"] = " ".join(sample.split())[:SAMPLE]
        entry["peer"] = peer[:64]
        _seen[name] = entry
        while len(_seen) > MAX:
            _seen.popitem(last=False)
    bus.publish("strangers")


def forget(protocol: str, key: str) -> None:
    with _lock:
        _seen.pop(f"{protocol}:{key}", None)
    bus.publish("strangers")


def listing() -> list[dict[str, Any]]:
    with _lock:
        return list(reversed(list(_seen.values())))


def clear() -> None:
    with _lock:
        _seen.clear()
