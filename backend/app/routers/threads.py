"""The inbox: list, open, mark, archive, delete with undo."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import CurrentAccount, DbSession
from ..meldungen import fehler
from ..models import THREAD_STATES, Thread, utcnow
from ..services import bus
from ..services import threads as threads_service

router = APIRouter(prefix="/api/threads", tags=["threads"])


class StateIn(BaseModel):
    ids: list[int] = Field(max_length=500)
    state: str


class ReadAllIn(BaseModel):
    view: Literal["inbox", "unread", "crit", "archived"] = "inbox"
    source_id: int | None = None


def _get(db: DbSession, thread_id: int) -> Thread:
    thread = db.get(Thread, thread_id)
    if thread is None or thread.deleted_at is not None:
        raise fehler("not_found", "This message is gone.", 404)
    return thread


@router.get("", summary="Threads of a view, newest first, 100 per page")
def listing(
    account: CurrentAccount,
    db: DbSession,
    view: Literal["inbox", "unread", "crit", "archived"] = "inbox",
    source_id: int | None = None,
    q: str = "",
    before: str | None = None,
) -> dict[str, Any]:
    return threads_service.listing(db, view, source_id, q, before)


@router.get("/counts", summary="Numbers for the side bar")
def counts(account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return threads_service.counts(db)


@router.get("/{thread_id}", summary="One thread with its events and pushes")
def read(thread_id: int, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return threads_service.detail(db, _get(db, thread_id))


@router.post("/state", summary="Mark read, unread or archived")
def set_state(payload: StateIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    if payload.state not in THREAD_STATES:
        raise fehler("invalid_state", "Unknown state.", 422)
    changed = threads_service.set_state(db, payload.ids, payload.state)
    for thread_id in changed:
        bus.publish("thread", id=thread_id)
    return {"changed": changed}


@router.post("/read-all", summary="Mark everything in a view as read")
def read_all(payload: ReadAllIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    changed = threads_service.mark_all_read(db, payload.view, payload.source_id)
    bus.publish("threads")
    return {"changed": len(changed)}


@router.delete("/{thread_id}", status_code=204, summary="Delete; can be undone for a few minutes")
def delete(thread_id: int, account: CurrentAccount, db: DbSession) -> None:
    thread = _get(db, thread_id)
    thread.deleted_at = utcnow()
    db.commit()
    bus.publish("thread", id=thread_id)


@router.post("/{thread_id}/restore", summary="Undo a delete")
def restore(thread_id: int, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise fehler("not_found", "Too late: this message is gone for good.", 404)
    thread.deleted_at = None
    db.commit()
    bus.publish("thread", id=thread_id)
    return threads_service.detail(db, thread)
