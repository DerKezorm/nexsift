"""What every door hands to the inbox: one normalized message.

An adapter turns what a sender sent into an ``Incoming``. Two rules hold for all of them:

1. **Nothing gets lost.** An adapter that does not understand a message still delivers it, as plain title and
   text with the sender's priority, and says so with ``recognized=False``. The source then shows that its
   format was not recognized, and the operator sees the raw data.
2. **Structured fields before text.** Where a sender has a status number or an id, that decides, not a
   sentence that may be worded differently in the next version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import CRIT, INFO, WARN

#: What is kept of a raw message. Enough to see the format, not enough to fill the disk.
RAW_MAX = 16_000
TITLE_MAX = 300
BODY_MAX = 8_000
URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


@dataclass
class Incoming:
    title: str
    body: str = ""
    priority: str = INFO
    links: list[dict[str, str]] = field(default_factory=list)
    raw: str = ""
    recognized: bool = True
    #: Values an adapter or rule can group by: {vmid}, {monitor}, {container} …
    fields: dict[str, str] = field(default_factory=dict)
    #: Set by adapters that know the all-clear of a problem (Uptime Kuma UP): closes the open thread with this key.
    resolves: str = ""
    #: Set by adapters that know what belongs together (Uptime Kuma: per monitor).
    group_key: str = ""

    def clean(self) -> Incoming:
        self.title = " ".join((self.title or "").split())[:TITLE_MAX] or "(no title)"
        self.body = (self.body or "").strip()[:BODY_MAX]
        self.raw = (self.raw or "")[:RAW_MAX]
        if self.priority not in (INFO, WARN, CRIT):
            self.priority = INFO
        self.links = [link for link in self.links if safe_url(link.get("url", ""))][:5]
        return self


def safe_url(url: str) -> bool:
    """Only http and https become buttons; a javascript: link in a message must never be clickable."""
    return url.lower().startswith(("http://", "https://")) and len(url) <= 2000


def links_from_text(*texts: str, label: str = "") -> list[dict[str, str]]:
    """Every address in the text as a button. The label is the host, unless the adapter knows better."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for text in texts:
        for match in URL.finditer(text or ""):
            url = match.group(0).rstrip(".,;:")
            if url in seen:
                continue
            seen.add(url)
            host = url.split("://", 1)[1].split("/", 1)[0]
            found.append({"label": label or host, "url": url})
    return found


def gotify_priority(value: object) -> str:
    """Gotify: 0 to 10. The official client sounds from 4 and pops up from 8; nexsift follows that."""
    try:
        number = int(str(value))
    except ValueError:
        return INFO
    if number >= 8:
        return CRIT
    if number >= 4:
        return WARN
    return INFO


def ntfy_priority(value: object) -> str:
    """ntfy: 1 to 5, or the words min, low, default, high, max/urgent."""
    text = str(value or "").strip().lower()
    words = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5, "urgent": 5}
    number = words.get(text)
    if number is None:
        try:
            number = int(text)
        except ValueError:
            number = 3
    if number >= 5:
        return CRIT
    if number == 4:
        return WARN
    return INFO


def word_priority(value: object) -> str | None:
    """A priority written as a word by a sender (critical, error, warning, info …). None: not recognized."""
    text = str(value or "").strip().lower()
    if text in ("crit", "critical", "emerg", "emergency", "alert", "error", "err", "fatal", "failure", "urgent"):
        return CRIT
    if text in ("warn", "warning", "high", "medium"):
        return WARN
    if text in ("info", "information", "notice", "debug", "low", "ok", "success", "unknown"):
        return INFO
    return None
