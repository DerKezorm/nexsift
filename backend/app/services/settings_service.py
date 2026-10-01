"""Operator settings in the database, with defaults. Secrets go through ``crypto.encrypt_secret`` first."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Setting

PUSH_MODES = ("immediate", "window", "single", "never")

DEFAULTS: dict[str, Any] = {
    "password_login": True,
    #: OIDC: issuer, client_id and the encrypted client secret; empty means not set up.
    "oidc_issuer": "",
    "oidc_client_id": "",
    "oidc_client_secret_enc": "",
    "oidc_provider_name": "",
    "public_url": "",
    #: What happens with a critical event when no rule says otherwise.
    "push_mode": "immediate",
    #: How long a thread stays open for more of the same, in minutes.
    "bundle_minutes": 15,
    #: Per source and minute; above it events are only counted.
    "throttle_per_minute": 30,
    #: Storm guard: from this many first pushes within this many minutes, only one summary.
    "storm_enabled": True,
    "storm_count": 5,
    "storm_minutes": 2,
    "retention_days": 90,
    "archive_days": 30,
    "raw_days": 7,
    #: Keys of the built-in rules already handed out once. One the operator deleted stays deleted.
    "installed_rules": [],
}

#: What the frontend may read and the operator may change through PUT /api/settings.
PUBLIC_KEYS = (
    "password_login",
    "public_url",
    "push_mode",
    "bundle_minutes",
    "throttle_per_minute",
    "storm_enabled",
    "storm_count",
    "storm_minutes",
    "retention_days",
    "archive_days",
    "raw_days",
)

#: Lower and upper bound for every number the operator can set. Outside: refused, not clamped silently.
BOUNDS: dict[str, tuple[int, int]] = {
    "bundle_minutes": (1, 1440),
    "throttle_per_minute": (1, 10000),
    "storm_count": (2, 100),
    "storm_minutes": (1, 60),
    "retention_days": (1, 3650),
    "archive_days": (1, 3650),
    "raw_days": (0, 365),
}


def get(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    return DEFAULTS.get(key) if row is None else row.value


def get_all(db: Session) -> dict[str, Any]:
    values = dict(DEFAULTS)
    for row in db.scalars(select(Setting)):
        values[row.key] = row.value
    return values


def public(db: Session) -> dict[str, Any]:
    values = get_all(db)
    return {key: values[key] for key in PUBLIC_KEYS}


def save(db: Session, values: dict[str, Any]) -> None:
    for key, value in values.items():
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    db.commit()


def normalize_public_url(value: str) -> str:
    """``scheme://host[:port]`` and nothing else, or empty. Raises ``ValueError`` otherwise."""
    text = value.strip()
    if not text:
        return ""
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("scheme or host")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("path, query or credentials")
    try:
        parts.port  # noqa: B018 - raises ValueError when the port is not a number
    except ValueError as error:
        raise ValueError("port") from error
    return f"{parts.scheme.lower()}://{parts.netloc}"


def public_url(db: Session) -> str:
    stored = str(get(db, "public_url") or "").strip().rstrip("/")
    if stored:
        return stored
    return get_settings().public_url.strip().rstrip("/")
