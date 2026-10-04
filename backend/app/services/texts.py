"""Words nexsift writes itself, in more than one language.

What an adapter understood is stored twice: as English title and body (search, rules and the API read those), and as
text keys with their values in ``Event.texts``. The interface shows the keys in the chosen language, the pushes in
``push_language``. The ``sender`` part of ``app/texts/<language>.json`` is the same as in the interface's language
files; a test holds the two together.

``texts`` looks like ``{"title": {"key": ..., "args": {...}}, "body": [[segment, ...], ...]}``: a body is lines of
segments, and a segment is ``{"key": ..., "args": {...}}`` or ``{"text": ...}`` for words that are not ours (a
monitor name, an address). Segments of a line are joined with " · ".
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

LANGUAGES = ("en", "de")
FALLBACK = "en"
_FOLDER = Path(__file__).resolve().parent.parent / "texts"
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")

Segment = dict[str, Any]
Texts = dict[str, Any]


@cache
def table(language: str) -> dict[str, Any]:
    return json.loads((_FOLDER / f"{language}.json").read_text(encoding="utf-8"))


def _lookup(language: str, key: str) -> str | None:
    node: Any = table(language)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def say(key: str, language: str = FALLBACK, /, **args: Any) -> str:
    """One text; with ``count`` the ``_one`` or ``_other`` form, like i18next in the interface."""
    if language not in LANGUAGES:
        language = FALLBACK
    candidates = [key]
    if "count" in args:
        candidates.insert(0, f"{key}_{'one' if args['count'] == 1 else 'other'}")
    for lang in (language, FALLBACK):
        for candidate in candidates:
            template = _lookup(lang, candidate)
            if template is not None:
                return _PLACEHOLDER.sub(lambda match: str(args.get(match.group(1), "")), template)
    return key


def key(name: str, /, **args: Any) -> Segment:
    return {"key": name, "args": args}


def text(value: str) -> Segment:
    return {"text": value}


def segment(part: Segment, language: str = FALLBACK) -> str:
    if "key" in part:
        return say(str(part["key"]), language, **dict(part.get("args") or {}))
    return str(part.get("text", ""))


def title(texts: Texts | None, language: str = FALLBACK) -> str | None:
    if not texts or not isinstance(texts.get("title"), dict):
        return None
    return segment(texts["title"], language)


def body(texts: Texts | None, language: str = FALLBACK) -> str | None:
    if not texts or not isinstance(texts.get("body"), list):
        return None
    lines = [" · ".join(segment(part, language) for part in line if isinstance(part, dict)) for line in texts["body"]]
    return "\n".join(line for line in lines if line)
