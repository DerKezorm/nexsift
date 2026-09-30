"""Rules: which message matters how much, what belongs together, what may reach the phone.

The same semantics as ``frontend/src/lib/rules.ts`` (the tester on the rules page shows what this does):
all matching rules apply, top to bottom; for every action the topmost rule that sets it wins, a lower one only
fills what is still open; "drop" ends the evaluation.

"word" matches whole words only, so a rule on ERROR does not fire on "0 errors" and one on "full" not on
"fullscreen". Several alternatives with a bar: ``FAIL|ERROR``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PRIORITIES, Rule
from . import settings_service

FIELDS = ("any", "title", "body")
OPS = ("word", "contains", "regex")
ACTIONS = ("priority", "group_key", "title_template", "resolves", "push", "drop")
VALUE_MAX = 300
#: What a regex is run against at most. A rule is the operator's own, but a pattern that backtracks badly on a
#: long message must not stall every door.
MATCH_TEXT_MAX = 4000


class RuleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@lru_cache(maxsize=512)
def _compile(op: str, value: str) -> re.Pattern[str] | None:
    try:
        if op == "regex":
            return re.compile(value, re.IGNORECASE)
        if op == "word":
            words = [re.escape(word.strip()) for word in value.split("|") if word.strip()]
            if not words:
                return None
            return re.compile(rf"(?<![\w])(?:{'|'.join(words)})(?![\w])", re.IGNORECASE)
    except re.error:
        return None
    return None


def condition_holds(op: str, value: str, text: str) -> bool:
    text = text[:MATCH_TEXT_MAX]
    if op == "contains":
        return value.lower() in text.lower()
    pattern = _compile(op, value)
    return bool(pattern and pattern.search(text))


def matches(rule: Rule | dict[str, Any], source_id: int, title: str, body: str) -> bool:
    data = rule if isinstance(rule, dict) else as_dict(rule)
    if not data.get("enabled", True):
        return False
    if data.get("source_id") and data["source_id"] != source_id:
        return False
    conditions = data.get("conditions") or []
    if not conditions:
        return False
    for condition in conditions:
        text = {"title": title, "body": body}.get(condition.get("field"), f"{title}\n{body}")
        if not condition_holds(condition.get("op", "word"), str(condition.get("value", "")), text):
            return False
    return True


@dataclass
class Outcome:
    matched: list[str] = field(default_factory=list)
    actions: dict[str, Any] = field(default_factory=dict)


def evaluate(rules: list[Rule] | list[dict[str, Any]], source_id: int, title: str, body: str) -> Outcome:
    outcome = Outcome()
    for rule in rules:
        data = rule if isinstance(rule, dict) else as_dict(rule)
        if not matches(data, source_id, title, body):
            continue
        outcome.matched.append(str(data.get("name", "")))
        for key, value in (data.get("actions") or {}).items():
            if key in ACTIONS and value not in (None, "", False) and key not in outcome.actions:
                outcome.actions[key] = value
        if (data.get("actions") or {}).get("drop"):
            break
    return outcome


def ordered(db: Session) -> list[Rule]:
    return list(db.scalars(select(Rule).order_by(Rule.position, Rule.id)))


def as_dict(rule: Rule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "position": rule.position,
        "name": rule.name,
        "enabled": rule.enabled,
        "source_id": rule.source_id,
        "conditions": rule.conditions or [],
        "actions": rule.actions or {},
        "built_in": rule.built_in,
    }


def fill(template: str, fields: dict[str, str]) -> str:
    """``vm-{vmid}`` with the values of the message. A placeholder without a value stays visible, so the thread
    title shows what is missing instead of silently merging unrelated messages."""
    return re.sub(r"\{(\w+)\}", lambda m: fields.get(m.group(1), m.group(0)), template)


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    """The rule as stored, or ``RuleError`` with a code the interface translates."""
    name = str(payload.get("name", "") or "").strip()
    if not name or len(name) > 120:
        raise RuleError("rule_name", "Give the rule a name (at most 120 characters).")
    conditions = []
    for condition in payload.get("conditions") or []:
        field_name = condition.get("field", "any")
        op = condition.get("op", "word")
        value = str(condition.get("value", "") or "")
        if field_name not in FIELDS or op not in OPS:
            raise RuleError("rule_condition", "Unknown field or comparison.")
        if not value.strip() or len(value) > VALUE_MAX:
            raise RuleError("rule_value", "Every condition needs a value (at most 300 characters).")
        if op == "regex":
            try:
                re.compile(value)
            except re.error as error:
                raise RuleError("rule_regex", f"The pattern is not valid: {error.msg}.") from error
        conditions.append({"field": field_name, "op": op, "value": value})
    if not conditions:
        raise RuleError("rule_no_condition", "A rule needs at least one condition.")
    actions: dict[str, Any] = {}
    raw = payload.get("actions") or {}
    if raw.get("priority"):
        if raw["priority"] not in PRIORITIES:
            raise RuleError("rule_priority", "Unknown priority.")
        actions["priority"] = raw["priority"]
    if raw.get("push"):
        if raw["push"] not in settings_service.PUSH_MODES:
            raise RuleError("rule_push", "Unknown push behaviour.")
        actions["push"] = raw["push"]
    for key in ("group_key", "title_template", "resolves"):
        value = str(raw.get(key, "") or "").strip()
        if len(value) > 200:
            raise RuleError("rule_value", "Keep grouping and titles under 200 characters.")
        if value:
            actions[key] = value
    if raw.get("drop"):
        actions = {"drop": True}
    if not actions:
        raise RuleError("rule_no_action", "A rule needs at least one action.")
    return {
        "name": name,
        "enabled": bool(payload.get("enabled", True)),
        "source_id": payload.get("source_id") or None,
        "conditions": conditions,
        "actions": actions,
    }
