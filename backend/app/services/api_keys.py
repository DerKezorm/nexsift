"""Read-only API keys for dashboards, and the operator's switch in front of them. Taken over from nextrmnl.

⚠️ Closed until the operator opens it. A key is a way out: what the homelab reported leaves nexsift and stands on a
dashboard afterwards, often one guests see. Whether that way exists in an installation is the operator's decision.

⚠️ Closing it deletes no key. The keys stay and are refused while it is closed, so a mistaken click does not cost
every dashboard in the house.

A key reads counts and the newest lines through ``/api/v1``, nothing else: no message text, no source token, no
target, no setting. It changes nothing.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ApiKey, utcnow
from . import settings_service

logger = logging.getLogger("nexsift.api")

#: How a nexsift key is recognised in a configuration file, by a secret scanner and by the log's scrubber.
PREFIX = "nxs_"
#: Enough for every dashboard in the house, and a limit against a list nobody oversees.
MAX_KEYS = 20
MAX_NAME = 64
#: How old ``last_used_at`` may get before it is written again: a dashboard asks every few seconds.
REMEMBER_EVERY = timedelta(minutes=1)


class KeyProblem(ValueError):
    """An input that does not fit. ``code`` is what the frontend translates."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def allowed(db: Session) -> bool:
    return bool(settings_service.get(db, "api_keys_allowed"))


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def create(db: Session, name: str) -> tuple[ApiKey, str]:
    """A new key; the plaintext is returned here and never again."""
    name = " ".join(name.split())
    if not name:
        raise KeyProblem("api_key_name_missing", "Give the key a name.")
    if len(name) > MAX_NAME:
        raise KeyProblem("api_key_name_too_long", f"The name may be {MAX_NAME} characters at most.")
    if (db.scalar(select(func.count()).select_from(ApiKey)) or 0) >= MAX_KEYS:
        raise KeyProblem("api_key_limit", f"There are already {MAX_KEYS} keys. Delete one first.")
    plaintext = PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(name=name, prefix=plaintext[:8], token_hash=_hash(plaintext))
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("API key created name=%s", name)
    return row, plaintext


def listing(db: Session) -> list[ApiKey]:
    return list(db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc(), ApiKey.id.desc())))


def delete(db: Session, key_id: int) -> bool:
    row = db.get(ApiKey, key_id)
    if row is None:
        return False
    logger.info("API key deleted name=%s", row.name)
    db.delete(row)
    db.commit()
    return True


def find(db: Session, plaintext: str) -> ApiKey | None:
    if not plaintext.startswith(PREFIX) or len(plaintext) > 200:
        return None
    row = db.scalar(select(ApiKey).where(ApiKey.token_hash == _hash(plaintext)))
    if row is None:
        return None
    now = utcnow()
    if row.last_used_at is None or now - row.last_used_at >= REMEMBER_EVERY:
        row.last_used_at = now
        db.commit()
    return row
