"""The operator's read-only API keys: list, create, delete."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import CurrentAccount, DbSession
from ..meldungen import fehler
from ..models import ApiKey
from ..services import api_keys

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=api_keys.MAX_NAME)


def _view(row: ApiKey) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "created_at": row.created_at.isoformat(),
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


@router.get("", summary="The API keys, newest first")
def listing(account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    return {"allowed": api_keys.allowed(db), "keys": [_view(row) for row in api_keys.listing(db)]}


@router.post("", status_code=201, summary="Create a key; the key itself is in this answer and never again")
def create(payload: KeyIn, account: CurrentAccount, db: DbSession) -> dict[str, Any]:
    try:
        row, plaintext = api_keys.create(db, payload.name)
    except api_keys.KeyProblem as error:
        raise fehler(error.code, str(error), 422) from error
    return {**_view(row), "key": plaintext}


@router.delete("/{key_id}", status_code=204, summary="Delete a key; every dashboard using it stops at once")
def delete(key_id: int, account: CurrentAccount, db: DbSession) -> None:
    if not api_keys.delete(db, key_id):
        raise fehler("not_found", "Key not found.", 404)
