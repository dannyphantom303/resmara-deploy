"""Encrypt the platform tokens we hold for other people at rest.

A Meta token is a credential to somebody else's ad account and to their money: an
ad-account read of `resmara.db` used to hand it over in plaintext. Every token column is
now written through :func:`encrypt` and read through :func:`decrypt`, so the database alone
is not enough to use a customer's account.

Key handling, in order of preference:

* ``RESMARA_TOKEN_KEY`` - a urlsafe-base64 32-byte Fernet key. **Set this in production**
  (and back it up: losing it means every stored token must be re-connected by hand).
* otherwise a key derived from ``SECRET_KEY`` with HKDF/SHA-256, so a dev box keeps working
  across restarts and the test suite needs no setup.

Old rows that still hold a bare token keep working: :func:`decrypt` passes anything without
the ``enc:`` prefix straight through, and :func:`rotate_plaintext_tokens` upgrades them.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

PREFIX = "enc:"


def _derive_key(secret: str) -> bytes:
    """HKDF-ish derivation: SHA-256 of a fixed label + the app secret, base64url-encoded."""
    digest = hashlib.sha256(b"resmara-token-key-v1:" + (secret or "").encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    raw = os.getenv("RESMARA_TOKEN_KEY", "").strip()
    if raw:
        try:
            return Fernet(raw.encode())
        except Exception:
            # A malformed key must not silently fall back to a weaker one.
            raise RuntimeError("RESMARA_TOKEN_KEY is not a valid urlsafe-base64 Fernet key")
    return Fernet(_derive_key(settings.SECRET_KEY))


def using_explicit_key() -> bool:
    """True when RESMARA_TOKEN_KEY is set (i.e. keys survive a SECRET_KEY change)."""
    return bool(os.getenv("RESMARA_TOKEN_KEY", "").strip())


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(plaintext) -> str:
    """Encrypt a secret for storage. Blank/None values stay blank (simulated accounts)."""
    if plaintext is None:
        return ""
    value = str(plaintext)
    if not value or is_encrypted(value):
        return value
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(stored) -> str:
    """Read a stored secret. Plaintext (legacy) values come back unchanged."""
    if stored is None:
        return ""
    value = str(stored)
    if not value or not is_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        # Wrong/rotated key: say so instead of handing back ciphertext that would be
        # sent to Meta as a token and produce a confusing OAuth error.
        raise TokenDecryptError(
            "stored token cannot be decrypted with the current key "
            "(RESMARA_TOKEN_KEY changed or missing) - reconnect the account"
        )


class TokenDecryptError(RuntimeError):
    pass


def rotate_plaintext_tokens(rows) -> int:
    """Encrypt any pre-existing plaintext token on the given AdAccount rows, in place.

    Idempotent: values already carrying the prefix are left alone. Returns the count
    changed. Called from the startup migration so an upgrade does not leave a plaintext
    token behind.
    """
    changed = 0
    for row in rows:
        for field in ("access_token", "refresh_token"):
            value = getattr(row, field, None)
            if value and not is_encrypted(value):
                setattr(row, field, encrypt(value))
                changed += 1
    return changed
