import hashlib
import secrets
import threading
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

# Argon2id at the OWASP-recommended minimum cost (19 MiB, t=2, p=1).
# Raise the cost for production hardware.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


_slots_lock = threading.Lock()
_slots_semaphore: threading.BoundedSemaphore | None = None


def _slots() -> threading.BoundedSemaphore:
    """Limits how many password hashes run at the same moment in this process.

    Created once, under a lock: if several first sign-ins arrived together and each made its own
    limiter, there would be no limit at all.
    """
    global _slots_semaphore
    if _slots_semaphore is None:
        with _slots_lock:
            if _slots_semaphore is None:
                _slots_semaphore = threading.BoundedSemaphore(
                    max(1, get_settings().max_concurrent_hashes)
                )
    return _slots_semaphore


def reset_hash_limit() -> None:
    """Forget the limiter so the next hash makes a new one from the current settings (tests)."""
    global _slots_semaphore
    with _slots_lock:
        _slots_semaphore = None


def hash_password(password: str) -> str:
    with _slots():
        return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        with _slots():
            return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


@lru_cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so unknown emails are not distinguishable by timing."""
    verify_password(_dummy_hash(), password)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Tokens are stored hashed; a database leak must not leak usable sessions or reset links."""
    return hashlib.sha256(raw.encode()).hexdigest()
