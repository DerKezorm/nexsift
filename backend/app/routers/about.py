"""Whether a newer nexsift is out: the answer, asking now, and the switch for the daily question.

nexsift has one operator account, so whoever is signed in may switch and ask.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from ..db import SessionLocal
from ..deps import CurrentAccount
from ..services import settings_service, updates

router = APIRouter(prefix="/api/about", tags=["about"])


class UpdatesOut(BaseModel):
    update_check: bool
    checked: bool = False
    latest: str | None = None
    newer: bool = False
    checked_at: datetime | None = None
    #: The release page of the newest version, when there is one.
    release_url: str | None = None


class UpdateSwitchIn(BaseModel):
    update_check: bool


def _on() -> bool:
    with SessionLocal() as db:
        return bool(settings_service.get(db, "update_check"))


def _out(on: bool, known: updates.State) -> UpdatesOut:
    return UpdatesOut(
        update_check=on,
        checked=known.checked_at is not None,
        latest=known.latest,
        newer=known.newer,
        checked_at=known.checked_at,
        release_url=f"{updates.RELEASES_URL}/tag/{known.latest}" if known.latest else None,
    )


@router.get("/updates", response_model=UpdatesOut, summary="Whether a newer nexsift is out (asked once a day)")
def update_state(account: CurrentAccount) -> UpdatesOut:
    on = _on()
    return _out(on, updates.state(on=on))


@router.post("/updates/check", response_model=UpdatesOut, summary="Ask now, also with the daily check off")
def check_now(account: CurrentAccount) -> UpdatesOut:
    """Off means "not by itself"; whoever clicks here has just decided."""
    return _out(_on(), updates.state(on=True, force=True))


@router.put("/updates", response_model=UpdatesOut, summary="Switch the daily check")
def switch(body: UpdateSwitchIn, account: CurrentAccount) -> UpdatesOut:
    with SessionLocal() as db:
        settings_service.save(db, {"update_check": body.update_check})
    if not body.update_check:
        updates.forget()
    return _out(body.update_check, updates.state(on=body.update_check))
