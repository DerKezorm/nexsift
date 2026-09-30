"""The operator account: created once at the first start, then signed in with password or OIDC."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, utcnow
from ..security import LOCK_MINUTES, MAX_FAILURES, hash_password, verify_password

logger = logging.getLogger("nexsift.auth")

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Account)) or 0)


def operator(db: Session) -> Account | None:
    return db.scalar(select(Account).order_by(Account.id).limit(1))


def by_name(db: Session, name: str) -> Account | None:
    return db.scalar(select(Account).where(Account.name == name.strip().lower()))


def create_operator(db: Session, name: str, password: str, email: str = "") -> Account:
    if count(db) > 0:
        raise AccountError("already_set_up", "nexsift is already set up.", 409)
    cleaned = name.strip().lower()
    if not NAME_PATTERN.match(cleaned):
        raise AccountError("invalid_name", "Use 2 to 64 letters, digits, dots, dashes or underscores.", 422)
    account = Account(name=cleaned, password_hash=hash_password(password), email=normalize_email(email))
    db.add(account)
    db.commit()
    logger.info("Operator account created name=%s", account.name)
    return account


def normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    if cleaned and not EMAIL_PATTERN.match(cleaned):
        raise AccountError("invalid_email", "This is not an email address.", 422)
    return cleaned


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Verified against when the name is unknown, so the answer takes as long as for a wrong password."""
    return hash_password(secrets.token_urlsafe(24))


def is_locked(account: Account) -> bool:
    return account.locked_until is not None and account.locked_until > utcnow()


def note_failure(db: Session, account: Account) -> None:
    account.failed_logins += 1
    if account.failed_logins >= MAX_FAILURES:
        account.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
        account.failed_logins = 0
        logger.warning("Account locked after %s failures name=%s", MAX_FAILURES, account.name)
    db.commit()


def note_success(db: Session, account: Account) -> None:
    account.failed_logins = 0
    account.locked_until = None
    account.last_seen_at = utcnow()
    db.commit()


def authenticate(db: Session, name: str, password: str) -> Account:
    account = by_name(db, name)
    if account is None:
        verify_password(password, _dummy_hash())
        logger.warning("Sign-in failed for unknown account %r", name.strip().lower()[:64])
        raise AccountError("wrong_credentials", "Name or password is wrong.", 401)
    if is_locked(account):
        raise AccountError("account_locked", "Too many failed sign-ins. Try again later.", 429)
    if not verify_password(password, account.password_hash):
        note_failure(db, account)
        raise AccountError("wrong_credentials", "Name or password is wrong.", 401)
    note_success(db, account)
    return account


def change_password(db: Session, account: Account, current: str, new: str) -> None:
    if not verify_password(current, account.password_hash):
        note_failure(db, account)
        raise AccountError("wrong_password", "The current password is wrong.", 401)
    account.password_hash = hash_password(new)
    db.commit()
    logger.info("Password changed name=%s", account.name)


def reset_password(db: Session, new: str) -> Account:
    """The emergency exit from the container (``python -m app.reset_password``): no old password needed."""
    account = operator(db)
    if account is None:
        raise AccountError("not_set_up", "nexsift is not set up yet.", 409)
    account.password_hash = hash_password(new)
    account.failed_logins = 0
    account.locked_until = None
    db.commit()
    logger.warning("Password reset from the command line name=%s", account.name)
    return account
