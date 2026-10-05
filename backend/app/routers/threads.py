"""The inbox: list, open, mark, archive, close by hand, delete with undo; one thread or several."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from ..deps import CurrentAccount, DbSession
from ..meldungen import fehler
from ..models import THREAD_STATES, Thread, utcnow
from ..services import bus, icons
from ..services import threads as threads_service

router = APIRouter(prefix="/api/threads", tags=["threads"])

# How many just-read threads may stay in "unread": more than anyone reads in one sitting.
KEEP = 500


class StateIn(BaseModel):
    ids: list[int] = Field(max_length=threads_service.BULK)
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
    keep: Annotated[list[int] | None, Query(max_length=KEEP)] = None,
) -> dict[str, Any]:
    """`keep`: threads read in "unread" that should stay in that list for now."""
    return threads_service.listing(db, view, source_id, q, before, keep)


@router.get("/counts", summary="Numbers for the side bar, optionally of one source")
def counts(account: CurrentAccount, db: DbSession, source_id: int | None = None) -> dict[str, Any]:
    return threads_service.counts(db, source_id)


@router.get("/{thread_id}", summary="One thread with its events and pushes")
def read(thread_id: int, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return threads_service.detail(db, _get(db, thread_id))


@router.get("/{thread_id}/icon", summary="The icon a rule gave this line", response_class=Response)
async def icon(thread_id: int, account: CurrentAccount, db: DbSession) -> Response:
    found = await icons.fetch(_get(db, thread_id).icon)
    if found is None:
        raise fehler("icon_unavailable", "The icon could not be loaded.", 404)
    data, kind = found
    return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/state", summary="Mark read, unread or archived")
def set_state(payload: StateIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    if payload.state not in THREAD_STATES:
        raise fehler("invalid_state", "Unknown state.", 422)
    changed = threads_service.set_state(db, payload.ids, payload.state)
    for thread_id in changed:
        bus.publish("thread", id=thread_id)
    return {"changed": changed}


class IdsIn(BaseModel):
    ids: list[int] = Field(max_length=threads_service.BULK)


class SourceIn(BaseModel):
    source_id: int | None = None


def _changed(changed: list[int]) -> dict[str, Any]:
    for thread_id in changed:
        bus.publish("thread", id=thread_id)
    return {"changed": changed}


@router.post("/resolve", summary="Close open problems by hand, as if the all-clear had come")
def resolve(payload: IdsIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return _changed(threads_service.resolve(db, payload.ids))


@router.post("/resolve-all", summary="Close everything in critical open, optionally of one source")
def resolve_all(payload: SourceIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return _changed(threads_service.resolve_all(db, payload.source_id))


@router.post("/reopen", summary="Undo closing by hand")
def reopen(payload: IdsIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return _changed(threads_service.reopen(db, payload.ids))


@router.post("/delete", summary="Delete several; can be undone for a few minutes")
def delete_many(payload: IdsIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return _changed(threads_service.delete(db, payload.ids))


@router.post("/restore", summary="Undo deleting several")
def restore_many(payload: IdsIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return _changed(threads_service.restore(db, payload.ids))


class ViewIn(BaseModel):
    #: "all": every thread, archived ones too (everything of a source).
    view: Literal["inbox", "unread", "crit", "archived", "all"] = "inbox"
    source_id: int | None = None


@router.post("/archive-all", summary="Everything of a view into the archive; the old states come back for the undo")
def archive_all(payload: ViewIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    before = threads_service.archive_all(db, payload.view, payload.source_id)
    bus.publish("threads")
    return {"changed": [thread_id for ids in before.values() for thread_id in ids], "before": before}


@router.post("/unarchive-all", summary="Everything in the archive back into the inbox")
def unarchive_all(payload: SourceIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    changed = threads_service.unarchive_all(db, payload.source_id)
    bus.publish("threads")
    return {"changed": changed}


@router.post("/delete-all", summary="Delete everything of a view; can be undone for a few minutes")
def delete_all(payload: ViewIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    changed = threads_service.delete_all(db, payload.view, payload.source_id)
    bus.publish("threads")
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
