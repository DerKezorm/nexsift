"""No log call may carry a secret as a value, and no message content outside the content logger.

The log says which source sent, which rule matched and which target was pushed to, never with what permission and
never with which credentials. This scan catches the obvious mistakes in the code: a format string like
``token=%s``, an f-string with ``{topic}`` in it, or an argument whose name says what it is (``payload.password``,
``config``, ``endpoint``). Counts, ids and booleans about secrets are fine (``has_token``, ``token_count``).

What a message said (``title``, ``body``, ``raw``, ``payload``) goes only to ``content_log``, the logger
``nexsift.content``, which writes at the level ``trace`` alone.

A legitimate exception, should one ever exist, goes into ``ALLOWED`` as the exact call text; today there is none.
``tests/test_log_leaks.py`` checks what really lands in the file.
"""

from __future__ import annotations

import ast
import re
from itertools import pairwise
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
#: Names of secrets in nexsift: the source token and ntfy topic, the targets' configuration and credentials, Web
#: Push addresses and keys, passwords, cookies and sessions.
KEYWORDS = {
    "password",
    "passphrase",
    "token",
    "secret",
    "topic",
    "endpoint",
    "p256dh",
    "auth",
    "cookie",
    "credential",
    "credentials",
    "config",
    "session",
    "subscription",
}
PLURALS = {"passwords", "tokens", "secrets", "topics", "endpoints", "cookies", "sessions", "private_keys"}
#: What a message said. Allowed in calls on the content logger only.
CONTENT = {"title", "body", "raw", "payload", "content", "text_body"}
CONTENT_LOGGERS = {"content_log"}
#: A component in front that turns a secret's name into a fact about it, and one at the end that makes it a count
#: or a reference.
FACT_PREFIXES = {"has", "is", "with", "without", "needs", "wants", "no"}
COUNT_SUFFIXES = {"count", "total", "len", "size", "id", "ids"}
#: Exact call texts (``ast.unparse`` of the call) that are allowed although the scan objects. Keep it empty.
ALLOWED: set[str] = set()
#: The app has at least this many log calls; fewer means the scan looked in the wrong place.
FLOOR = 60

#: ``label=%s``, ``label: %r``, ``label={x}`` in a format string.
LABEL_BEFORE_VALUE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*(?:%|\{)")
NAMED_PLACEHOLDER = re.compile(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)")


def names_a_secret(identifier: str, content_allowed: bool = False) -> bool:
    """Whether an identifier, by its components, is a secret (or content) rather than a fact or a count."""
    lowered = identifier.lower()
    if lowered in PLURALS:
        return True
    parts = lowered.split("_")
    if parts[0] in FACT_PREFIXES or parts[-1] in COUNT_SUFFIXES:
        return False
    if any(part in KEYWORDS for part in parts):
        return True
    if not content_allowed and (lowered in CONTENT or parts[-1] in CONTENT):
        return True
    return any(a == "private" and b == "key" for a, b in pairwise(parts))


def logger_name(node: ast.Call) -> str:
    root = node.func.value  # type: ignore[attr-defined]
    return getattr(root, "id", "") or getattr(root, "attr", "")


def is_log_call(node: ast.Call) -> bool:
    target = node.func
    if not isinstance(target, ast.Attribute) or target.attr not in LOG_METHODS:
        return False
    root = target.value
    if isinstance(root, ast.Call):
        return "getLogger" in ast.unparse(root.func)
    name = getattr(root, "id", "") or getattr(root, "attr", "")
    return "log" in name.lower()


def offending_in_format(text: str, content_allowed: bool) -> list[str]:
    labels = LABEL_BEFORE_VALUE.findall(text) + NAMED_PLACEHOLDER.findall(text)
    return [label for label in labels if names_a_secret(label, content_allowed)]


def offending_in_expression(source: str, content_allowed: bool) -> list[str]:
    if source.startswith("len(") and source.endswith(")"):
        return []  # a length is never the secret
    # Attribute chains count by their last name: ``payload.minutes`` is a number, ``payload.password`` a secret.
    tree = ast.parse(source, mode="eval")
    owners = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names = [
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) or (isinstance(node, ast.Name) and id(node) not in owners)
    ]
    # Keys of a dict handed over (``extra={"topic": …}``) name what they carry.
    names += [
        key.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    ]
    return [name for name in dict.fromkeys(names) if names_a_secret(name, content_allowed)]


def offending(node: ast.Call) -> list[str]:
    """What a log call gives away, by name. Empty when nothing."""
    content_allowed = logger_name(node) in CONTENT_LOGGERS
    arguments = list(node.args)
    if isinstance(node.func, ast.Attribute) and node.func.attr == "log":
        arguments = arguments[1:]
    found: list[str] = []
    for index, argument in enumerate(arguments):
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            found += offending_in_format(argument.value, content_allowed)
        elif isinstance(argument, ast.JoinedStr):
            for part in argument.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    found += offending_in_format(part.value, content_allowed)
                elif isinstance(part, ast.FormattedValue):
                    found += offending_in_expression(ast.unparse(part.value), content_allowed)
        elif index > 0:
            found += offending_in_expression(ast.unparse(argument), content_allowed)
    for keyword in node.keywords:
        if keyword.arg not in ("exc_info", "stack_info", "stacklevel"):
            found += offending_in_expression(ast.unparse(keyword.value), content_allowed)
    return list(dict.fromkeys(found))


def scan(source: str, origin: str = "<snippet>") -> list[tuple[str, int, str, list[str]]]:
    tree = ast.parse(source, filename=origin)
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and is_log_call(node):
            results.append((origin, node.lineno, ast.unparse(node), offending(node)))
    return results


def test_no_log_call_carries_a_secret() -> None:
    calls = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" not in path.parts:
            calls += scan(path.read_text(encoding="utf-8"), str(path.relative_to(APP.parent)))
    assert len(calls) >= FLOOR, f"only {len(calls)} log calls found; is the scan looking at the app?"
    bad = [
        f"{origin}:{line}: {', '.join(names)} in {text}"
        for origin, line, text, names in calls
        if names and text not in ALLOWED
    ]
    assert not bad, "Secrets in log calls:\n" + "\n".join(bad)
    stale = ALLOWED - {text for _origin, _line, text, _names in calls}
    assert not stale, f"ALLOWED names calls that no longer exist: {stale}"


def test_the_scan_knows_a_secret_when_it_sees_one() -> None:
    assert scan('logger.info("pw=%s", password)')[0][3] == ["password"]
    assert scan('logger.info("password=%s", value)')[0][3] == ["password"]
    assert scan('logger.warning("token: %r", request.headers)')[0][3] == ["token"]
    assert scan('logger.debug(f"key {private_key} loaded")')[0][3] == ["private_key"]
    assert scan('logger.debug("%(secret)s", {"secret": s})')[0][3] == ["secret"]
    assert scan('logger.info("Taken in", extra={"topic": name})')[0][3] == ["topic"]
    assert scan('logger.info("Sign-in name=%s", payload.password)')[0][3] == ["password"]
    assert scan('logger.info("Client secret_key=%s", x)')[0][3] == ["secret_key"]
    assert scan('logger.info("%s", source.token_enc)')[0][3] == ["token_enc"]
    assert scan('logger.info("%s", token_hash)')[0][3] == ["token_hash"]
    assert scan('logger.info("Push to %s", push.target_config(target))')[0][3] == ["target_config"]
    assert scan('logger.info("Device %s", config["url"])')[0][3] == ["config"]
    assert scan('logger.info("Push to endpoint=%s", url)')[0][3] == ["endpoint"]
    assert scan('logger.info("keys %s", subscription.p256dh)')[0][3] == ["p256dh"]
    assert scan('logger.info("keys %s", subscription)')[0][3] == ["subscription"]
    assert scan('logger.info("cookie=%s", value)')[0][3] == ["cookie"]
    assert scan('logging.getLogger("x").info("%s", topics)')[0][3] == ["topics"]


def test_what_a_message_said_goes_to_the_content_logger_only() -> None:
    assert scan('logger.debug("Message %s", item.title)')[0][3] == ["title"]
    assert scan('logger.debug("Message body=%r", text)')[0][3] == ["body"]
    assert scan('logger.debug("Raw %s", event.raw)')[0][3] == ["raw"]
    assert scan('content_log.debug("Message title=%r body=%r", item.title, item.body)')[0][3] == []
    assert scan('content_log.debug("Message token=%s", source.token)')[0][3] == ["token"], "secrets stay out there too"


def test_the_scan_lets_facts_and_counts_through() -> None:
    assert (
        scan('logger.info("Source created id=%s name=%s door=%s", source.id, source.name, source.protocol)')[0][3] == []
    )
    assert scan('logger.info("Target created name=%s kind=%s", target.name, target.kind)')[0][3] == []
    assert scan('logger.info("Key added has_token=%s", bool(x))')[0][3] == []
    assert scan('logger.info("Sign-in failed for unknown account %r", name)')[0][3] == []
    assert scan('logger.info("%s keys", len(payload.keys))')[0][3] == []
    assert scan('logger.info("Muted minutes=%s", payload.minutes)')[0][3] == [], "the owner is not the value"
    assert scan('logger.info("token_count=%s", len(tokens))')[0][3] == []
    assert scan('logger.info("source_id=%s", source_id)')[0][3] == []
    assert scan('logger.exception("Unhandled error on %s %s", method, path)')[0][3] == []
    assert scan('logger.info("authentik setup step %s done", key)')[0][3] == [], "authentik is not auth"
    assert scan('print("password=%s" % password)') == [], "not a log call"
