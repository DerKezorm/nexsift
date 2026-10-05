"""An icon per source: a logo from dashboard-icons or selfh.st, or an address of the operator's own.

Two readers want it. The phone (ntfy, web push) fetches the picture itself, so it gets a public address: the
collections' PNG on jsdelivr, or the operator's own. ntfy shows PNG and JPEG only, which is why the picker lists
the PNG folders and nothing else. The interface never talks to a CDN (the content security policy allows images
from nexsift only); it asks nexsift, which fetches and keeps a copy on disk.

What a source stores: ``""`` (none), ``dashboard-icons/<name>``, ``selfhst/<name>`` or an http(s) address.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path

import httpx

from ..config import get_settings

logger = logging.getLogger("nexsift.icons")

COLLECTIONS: dict[str, tuple[str, str]] = {
    "dashboard-icons": (
        "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/{name}.png",
        "https://api.github.com/repos/homarr-labs/dashboard-icons/git/trees/main?recursive=1",
    ),
    "selfhst": (
        "https://cdn.jsdelivr.net/gh/selfhst/icons/png/{name}.png",
        "https://api.github.com/repos/selfhst/icons/git/trees/main?recursive=1",
    ),
}
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
OWN_MAX = 500
#: What nexsift keeps of a picture: a logo is a few KB, this is plenty and keeps a wrong address from filling
#: the disk.
IMAGE_MAX = 1_000_000
#: No SVG: it can carry script, and opened directly it would run under nexsift's address.
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
INDEX_SECONDS = 86400
COPY_SECONDS = 14 * 86400
MISS_SECONDS = 3600
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
#: Tests set an ``httpx.MockTransport`` here.
transport_for_tests: httpx.BaseTransport | None = None

_index: dict[str, tuple[float, list[str]]] = {}
_missing: dict[str, float] = {}


class IconError(ValueError):
    pass


def normalize(value: str) -> str:
    """What the operator picked, checked: a collection logo or an own http(s) address. Raises ``IconError``."""
    value = value.strip()
    if not value:
        return ""
    if value.lower().startswith(("https://", "http://")):
        if len(value) > OWN_MAX or any(char.isspace() for char in value):
            raise IconError("This address cannot be an icon.")
        return value
    collection, _, name = value.partition("/")
    if collection not in COLLECTIONS or not NAME.match(name):
        raise IconError("Pick a logo from the list or enter an address starting with https://.")
    return f"{collection}/{name}"


def public_url(icon: str) -> str:
    """The address a phone can load the picture from, or "" when the source has none."""
    if not icon:
        return ""
    if icon.lower().startswith(("https://", "http://")):
        return icon
    collection, _, name = icon.partition("/")
    if collection not in COLLECTIONS or not NAME.match(name):
        return ""
    return COLLECTIONS[collection][0].format(name=name)


def version(icon: str) -> str:
    """Part of the interface's image address, so a new icon is loaded and not taken from the browser cache."""
    return hashlib.sha256(icon.encode("utf-8")).hexdigest()[:10] if icon else ""


def _cache_dir() -> Path:
    directory = get_settings().data_dir / "cache" / "icons"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


#: One client for the whole process. ⚠️ A fresh one loads the CA bundle on the event loop: 0.5 s each, measured on
#: 05.10.2026. The picker asks for thirty logos at once on a fresh installation, and with a client each the server
#: stood still for fifteen seconds; the walk found it, the picture in the dialog never came. nexdeck learned the
#: same on 09.09.2026.
_shared: httpx.AsyncClient | None = None
_shared_transport: httpx.BaseTransport | None = None


def _client() -> httpx.AsyncClient:
    global _shared, _shared_transport
    if _shared is None or _shared.is_closed or _shared_transport is not transport_for_tests:
        _shared = httpx.AsyncClient(
            timeout=TIMEOUT, transport=transport_for_tests, follow_redirects=True, headers={"User-Agent": "nexsift"}
        )
        _shared_transport = transport_for_tests
    return _shared


async def close() -> None:
    """Shutdown: let go of the connections the client holds open."""
    global _shared
    if _shared is not None and not _shared.is_closed:
        await _shared.aclose()
    _shared = None


async def fetch(icon: str) -> tuple[bytes, str] | None:
    """The picture for the interface, from the copy on disk or fetched once. None when there is none."""
    url = public_url(icon)
    if not url:
        return None
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    copy, kind_file = _cache_dir() / key, _cache_dir() / f"{key}.type"
    if copy.exists() and kind_file.exists() and time.time() - copy.stat().st_mtime < COPY_SECONDS:
        return copy.read_bytes(), kind_file.read_text(encoding="ascii")
    if _missing.get(key, 0) > time.monotonic():
        return None
    try:
        async with _client().stream("GET", url) as response:
            kind = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if response.status_code != 200 or kind not in IMAGE_TYPES:
                raise IconError(f"HTTP {response.status_code}, {kind or 'no type'}")
            data = b""
            async for chunk in response.aiter_bytes():
                data += chunk
                if len(data) > IMAGE_MAX:
                    raise IconError("larger than 1 MB")
    except (httpx.HTTPError, httpx.InvalidURL, IconError) as error:
        # The address may carry a token of the operator's; the log says what failed, not where.
        logger.info("Icon not loaded: %s", error if isinstance(error, IconError) else type(error).__name__)
        _remember_miss(key)
        return None
    if not data:
        _remember_miss(key)
        return None
    copy.write_bytes(data)
    kind_file.write_text(kind, encoding="ascii")
    return data, kind


def _remember_miss(key: str) -> None:
    now = time.monotonic()
    _missing[key] = now + MISS_SECONDS
    if len(_missing) > 500:
        for old in [name for name, until in _missing.items() if until <= now]:
            _missing.pop(old, None)


async def _names(collection: str) -> list[str]:
    hit = _index.get(collection)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    file = _cache_dir() / f"index-{collection}.json"
    if file.exists() and time.time() - file.stat().st_mtime < INDEX_SECONDS:
        names = json.loads(file.read_text(encoding="utf-8"))
        _index[collection] = (time.monotonic() + INDEX_SECONDS, names)
        return names
    names: list[str] = []
    try:
        response = await _client().get(COLLECTIONS[collection][1], headers={"Accept": "application/vnd.github+json"})
        if response.status_code == 200:
            for entry in response.json().get("tree", []):
                path = str(entry.get("path", ""))
                if path.startswith("png/") and path.endswith(".png"):
                    name = path[4:-4]
                    if NAME.match(name):
                        names.append(name)
    except (httpx.HTTPError, ValueError) as error:
        logger.info("Icon list %s unavailable: %s", collection, type(error).__name__)
    names = sorted(set(names))
    if names:
        file.write_text(json.dumps(names), encoding="utf-8")
    elif file.exists():
        # GitHub did not answer (rate limit, no internet): yesterday's list is better than none.
        names = json.loads(file.read_text(encoding="utf-8"))
    _index[collection] = (time.monotonic() + (INDEX_SECONDS if names else 300), names)
    return names


async def all_names() -> list[dict[str, str]]:
    """Every logo of both collections, each name once (dashboard-icons first), sorted: the picker browses this."""
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for collection in COLLECTIONS:
        for name in await _names(collection):
            if name not in seen:
                seen.add(name)
                results.append({"name": name, "icon": f"{collection}/{name}"})
    results.sort(key=lambda entry: entry["name"])
    return results


def reset_for_tests() -> None:
    _index.clear()
    _missing.clear()
