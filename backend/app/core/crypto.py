"""Encrypting small secrets stored in the database (authenticator-app keys).

Uses Fernet (AES-128-CBC with an HMAC) from the `cryptography` package, keyed from PIANO_SECRET_KEY.
A database backup on its own therefore does not reveal anyone's two-factor key. Changing the secret
key makes stored keys unreadable, so people would have to set two-factor up again.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"piano-totp-v1:" + get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str | None:
    """The original text, or None if it cannot be read (wrong key, damaged)."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None
