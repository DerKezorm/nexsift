"""Rules: list in order, create, change, move, delete, and try a message against them."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import CurrentAccount, DbSession
from ..meldungen import fehler
from ..models import Rule, Source
from ..services import presets, rules

logger = logging.getLogger("nexsift.rules")

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleIn(BaseModel):
    name: str = Field(max_length=120)
    enabled: bool = True
    source_id: int | None = None
    conditions: list[dict[str, Any]] = Field(max_length=10)
    actions: dict[str, Any]


class OrderIn(BaseModel):
    ids: list[int] = Field(max_length=1000)


class TryIn(BaseModel):
    source_id: int | None = None
    title: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=4000)


def _clean(db: DbSession, payload: RuleIn) -> dict[str, Any]:
    try:
        data = rules.validate(payload.model_dump())
    except rules.RuleError as error:
        raise fehler(error.code, str(error), 422) from error
    if data["source_id"] is not None and db.get(Source, data["source_id"]) is None:
        raise fehler("not_found", "Source not found.", 404)
    return data


@router.get("", summary="All rules, in the order they are checked")
def listing(account: CurrentAccount, db: DbSession) -> list[dict[str, Any]]:
    return [rules.as_dict(rule) for rule in rules.ordered(db)]


@router.post("", status_code=201, summary="New rule; lands above the general rules")
def create(payload: RuleIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    data = _clean(db, payload)
    last = db.scalar(select(func.max(Rule.position)).where(Rule.position < presets.DEFAULT_RULE_POSITION)) or 0
    rule = Rule(position=last + 10, **data)
    db.add(rule)
    db.commit()
    logger.info("Rule created id=%s name=%s", rule.id, rule.name)
    return rules.as_dict(rule)


@router.put("/order", summary="New order, top first")
def reorder(payload: OrderIn, account: CurrentAccount, db: DbSession) -> list[dict[str, Any]]:
    known = {rule.id: rule for rule in rules.ordered(db)}
    if sorted(payload.ids) != sorted(known):
        raise fehler("order_incomplete", "The order must name every rule exactly once.", 422)
    for index, rule_id in enumerate(payload.ids):
        known[rule_id].position = (index + 1) * 10
    db.commit()
    logger.info("Rules reordered count=%s", len(payload.ids))
    return [rules.as_dict(rule) for rule in rules.ordered(db)]


@router.post("/try", summary="Which rules match this message, and what comes out")
def try_message(payload: TryIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    outcome = rules.evaluate(rules.ordered(db), payload.source_id or 0, payload.title, payload.body)
    return {"matched": outcome.matched, "actions": outcome.actions}


@router.put("/{rule_id}", summary="Change a rule")
def update(rule_id: int, payload: RuleIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise fehler("not_found", "Rule not found.", 404)
    for key, value in _clean(db, payload).items():
        setattr(rule, key, value)
    db.commit()
    logger.info("Rule changed id=%s name=%s enabled=%s", rule.id, rule.name, rule.enabled)
    return rules.as_dict(rule)


@router.delete("/{rule_id}", status_code=204, summary="Delete a rule")
def delete(rule_id: int, account: CurrentAccount, db: DbSession) -> None:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise fehler("not_found", "Rule not found.", 404)
    name = rule.name
    db.delete(rule)
    db.commit()
    logger.info("Rule deleted id=%s name=%s", rule_id, name)
