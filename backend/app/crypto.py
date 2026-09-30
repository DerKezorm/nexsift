"""Server-side secrets: values the server must read on its own (OIDC client secret, source tokens, push
credentials). Encrypted with AES-256-GCM under a key derived from ``secret.key``; that is why the key belongs in
every backup of the data directory."""

from __future__ import annotations

import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

NONCE_BYTES = 12
AAD_SERVER = b"nexsift-server-secret-v1"


def _server_key() -> bytes:
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexsift-secrets:" + secret).digest()


def encrypt_secret(text: str) -> str:
    """Stored as hex. Empty stays empty."""
    if not text:
        return ""
    nonce = os.urandom(NONCE_BYTES)
    return (nonce + AESGCM(_server_key()).encrypt(nonce, text.encode("utf-8"), AAD_SERVER)).hex()


def decrypt_secret(stored: str) -> str:
    if not stored:
        return ""
    try:
        raw = bytes.fromhex(stored)
        if len(raw) < NONCE_BYTES + 16:
            return ""
        return AESGCM(_server_key()).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], AAD_SERVER).decode("utf-8")
    except (InvalidTag, ValueError):
        # A different secret.key than the one that encrypted it: the value is lost, not the app.
        return ""
