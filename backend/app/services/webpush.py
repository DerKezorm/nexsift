"""Web Push: notifications straight to a browser or an installed app, without ntfy or Gotify in between.

A device signs up in the interface; the browser hands over an address at its push service (Google, Apple or
Mozilla) and two keys. nexsift encrypts every message for that device (RFC 8291, aes128gcm) and signs the request
with its own key pair (VAPID, RFC 8292), so the push service only sees that something arrives, not what.

The way out goes through the browser maker's servers, so it is behind a switch that is off until the operator turns
it on (``webpush_enabled``).
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any
from urllib.parse import urlsplit

import http_ece
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy.orm import Session

from .. import crypto
from . import settings_service

#: How long a push service keeps a message for a device that is offline, in seconds.
TTL_SECONDS = 24 * 3600
#: How long a signature is valid; push services refuse more than a day.
VAPID_SECONDS = 12 * 3600
#: What the push service may hold for a device: the payload is small JSON, far below the 4 KB limit.
BODY_MAX = 1000


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def server_key(db: Session) -> ec.EllipticCurvePrivateKey:
    """nexsift's own key pair, made once and kept encrypted. Every device signed up is bound to its public half:
    a new pair would mean signing every device up again."""
    stored = str(settings_service.get(db, "webpush_key_enc") or "")
    if stored:
        pem = crypto.decrypt_secret(stored).encode("ascii")
        key = serialization.load_pem_private_key(pem, password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return key
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")
    settings_service.save(db, {"webpush_key_enc": crypto.encrypt_secret(pem)})
    return key


def public_key(db: Session) -> str:
    """The application server key the browser needs to sign up (base64url, uncompressed point)."""
    return b64url(_public_bytes(server_key(db)))


def encrypt(
    plaintext: bytes,
    p256dh: str,
    auth: str,
    *,
    sender: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """The message body for one device (RFC 8291). ``sender`` and ``salt`` are fresh for every message; tests pass
    the values of the RFC's example to check the result byte for byte."""
    return http_ece.encrypt(
        plaintext,
        salt=salt or os.urandom(16),
        private_key=sender or ec.generate_private_key(ec.SECP256R1()),
        dh=unb64url(p256dh),
        auth_secret=unb64url(auth),
        version="aes128gcm",
    )


def vapid_header(key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str, now: float | None = None) -> str:
    """``Authorization: vapid t=…, k=…`` for one push service (RFC 8292)."""
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int((now or time.time()) + VAPID_SECONDS),
        "sub": subject,
    }
    token = jwt.encode(claims, key, algorithm="ES256", headers={"typ": "JWT"})
    return f"vapid t={token}, k={b64url(_public_bytes(key))}"


def subject(db: Session) -> str:
    """Who sends, for the push service to contact. Apple refuses addresses on localhost, so a public https address
    if there is one, else an invented mail address that is at least well formed."""
    public = settings_service.public_url(db)
    if public.startswith("https://"):
        return public
    return "mailto:nexsift@example.com"


def payload(title: str, body: str, priority: str, url: str, tag: str) -> bytes:
    """What the service worker shows. Short: some push services refuse more than 4 KB after encryption."""
    data: dict[str, Any] = {"title": title[:200], "body": body[:BODY_MAX], "priority": priority, "url": url}
    if tag:
        data["tag"] = tag
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def valid_subscription(endpoint: str, p256dh: str, auth: str) -> bool:
    """What the browser handed over looks like a real sign-up: an https address and keys of the right size."""
    if not endpoint.lower().startswith("https://") or len(endpoint) > 1000:
        return False
    try:
        return len(unb64url(p256dh)) == 65 and unb64url(p256dh)[0] == 4 and len(unb64url(auth)) == 16
    except ValueError:
        return False
