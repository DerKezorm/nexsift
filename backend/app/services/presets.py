"""What nexsift offers when the operator adds a source, and the rules that come with it.

A preset decides the door (protocol), the adapter (kind) and a few built-in rules that make the sender behave
well from the first message on: Watchtower's updates bundle into one line and never ring the phone, Paperless'
documents the same. Built-in rules can be switched off or edited like any other.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CRIT, WARN, Rule
from . import settings_service

PRESETS: dict[str, dict[str, str]] = {
    "watchtower": {"kind": "watchtower", "protocol": "gotify", "name": "Watchtower"},
    "proxmox": {"kind": "proxmox", "protocol": "webhook", "name": "Proxmox VE"},
    "uptimekuma": {"kind": "uptimekuma", "protocol": "webhook", "name": "Uptime Kuma"},
    "homeassistant": {"kind": "homeassistant", "protocol": "ntfy", "name": "Home Assistant"},
    "synology": {"kind": "synology", "protocol": "webhook", "name": "Synology"},
    "paperless": {"kind": "paperless", "protocol": "webhook", "name": "Paperless-ngx"},
    "ups": {"kind": "ups", "protocol": "smtp", "name": "UPS"},
    "syslog": {"kind": "syslog", "protocol": "syslog", "name": "Router"},
    "gotify": {"kind": "generic", "protocol": "gotify", "name": "Gotify sender"},
    "ntfy": {"kind": "generic", "protocol": "ntfy", "name": "ntfy sender"},
    "discord": {"kind": "generic", "protocol": "discord", "name": "Discord sender"},
    "webhook": {"kind": "generic", "protocol": "webhook", "name": "Script"},
    "email": {"kind": "email", "protocol": "smtp", "name": "Email sender"},
}

#: Built-in rules per preset, created with the source and bound to it.
SOURCE_RULES: dict[str, list[dict[str, Any]]] = {
    "watchtower": [
        {
            "name": "Watchtower: bundle updates, never push them",
            "conditions": [{"field": "title", "op": "word", "value": "Updated"}],
            "actions": {"title_template": "Watchtower: {count} containers updated", "push": "never"},
        }
    ],
    "paperless": [
        {
            "name": "Paperless: bundle new documents, never push them",
            "conditions": [{"field": "any", "op": "regex", "value": ".+"}],
            "actions": {"title_template": "Paperless: {count} new documents", "push": "never"},
        }
    ],
    "syslog": [
        {
            "name": "sshd: failed sign-ins in one line",
            "conditions": [{"field": "title", "op": "regex", "value": r"sshd.*(Failed password|Invalid user)"}],
            "actions": {
                "group_key": "sshd-failed",
                "priority": WARN,
                "title_template": "sshd: {count} failed sign-ins",
            },
        }
    ],
}

#: Rules for every source, created at the first start after the built-in source rules (so those win).
DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "key": "keywords-critical",
        "name": "Words for failures make it critical",
        "conditions": [{"field": "any", "op": "word", "value": "FAIL|FAILED|FAILURE|CRITICAL|ERROR|FATAL|PANIC"}],
        "actions": {"priority": CRIT},
    },
    {
        "key": "keywords-warning",
        "name": "Words for trouble make it a warning",
        "conditions": [{"field": "any", "op": "word", "value": "WARN|WARNING|DEGRADED|RUNNING OUT"}],
        "actions": {"priority": WARN},
    },
]

#: Positions: source rules first, general ones after, so a sender-specific rule beats a keyword rule.
SOURCE_RULE_POSITION = 100
DEFAULT_RULE_POSITION = 1000


def install_defaults(db: Session) -> None:
    """Hands out each built-in rule once. Runs at every start, so it remembers what it gave: a rule the operator
    deleted would otherwise be back after the next update."""
    installed = list(settings_service.get(db, "installed_rules") or [])
    for index, rule in enumerate(DEFAULT_RULES):
        if rule["key"] in installed:
            continue
        installed.append(rule["key"])
        if db.scalar(select(Rule).where(Rule.built_in == rule["key"])) is None:
            db.add(
                Rule(
                    name=rule["name"],
                    position=DEFAULT_RULE_POSITION + index * 10,
                    conditions=rule["conditions"],
                    actions=rule["actions"],
                    built_in=rule["key"],
                )
            )
    settings_service.save(db, {"installed_rules": installed})


def install_source_rules(db: Session, preset: str, source_id: int) -> None:
    rules = SOURCE_RULES.get(preset, [])
    if not rules:
        return
    last = db.scalar(select(func.max(Rule.position)).where(Rule.position < DEFAULT_RULE_POSITION)) or 0
    position = max(last, SOURCE_RULE_POSITION - 10)
    for rule in rules:
        position += 10
        db.add(
            Rule(
                name=rule["name"],
                position=position,
                source_id=source_id,
                conditions=rule["conditions"],
                actions=rule["actions"],
                built_in=f"{preset}:{source_id}",
            )
        )
    db.commit()
