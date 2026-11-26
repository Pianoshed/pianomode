"""Two-factor sign-in with an authenticator app, plus one-time recovery codes.

- Setup stores an encrypted key but does nothing until the person proves their app works by
  typing a code (`enable`). Enabling shows ten recovery codes once; only hashes are stored.
- Signing in then needs a current code (or an unused recovery code). A code works once.
- Turning it off needs the password and a code, so a stolen session alone cannot remove it.
- Administrators must have it on before they can open admin tools (see `require_roles`).
"""

import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import crypto, totp
from app.core.errors import AppError, ConflictError
from app.core.security import hash_token, verify_password
from app.models.base import utcnow
from app.models.user import User

ISSUER = "Keystudy"
RECOVERY_CODES = 10


class TwoFactorRequiredError(AppError):
    status_code = 401
    code = "two_factor_required"


class InvalidCodeError(AppError):
    status_code = 401
    code = "invalid_code"


@dataclass(frozen=True)
class Setup:
    secret: str
    uri: str


def is_enabled(user: User) -> bool:
    return user.totp_enabled_at is not None


def _secret(user: User) -> str | None:
    return crypto.decrypt(user.totp_secret) if user.totp_secret else None


def begin_setup(session: Session, user: User) -> Setup:
    if is_enabled(user):
        raise ConflictError("Two-factor sign-in is already on.", code="two_factor_already_on")
    if user.email is None:
        raise ConflictError(
            "This login cannot use two-factor sign-in.", code="two_factor_unavailable"
        )
    secret = totp.new_secret()
    user.totp_secret = crypto.encrypt(secret)
    session.commit()
    return Setup(secret=secret, uri=totp.otpauth_uri(secret, user.email, ISSUER))


def _new_recovery_codes(user: User) -> list[str]:
    codes = [totp.recovery_code() for _ in range(RECOVERY_CODES)]
    user.recovery_codes = [hash_token(c) for c in codes]
    return codes


def enable(session: Session, user: User, code: str, now: float | None = None) -> list[str]:
    """Turn it on once a code from the app is right. Returns the recovery codes (shown once)."""
    secret = _secret(user)
    if is_enabled(user) or secret is None:
        raise ConflictError("Start two-factor setup first.", code="two_factor_not_started")
    step = totp.verify(secret, code, now if now is not None else time.time())
    if step is None:
        raise InvalidCodeError(
            "That code is not right. Check the time on your phone and try again."
        )
    user.totp_enabled_at = utcnow()
    user.totp_last_step = step
    codes = _new_recovery_codes(user)
    session.commit()
    return codes


def check_code(session: Session, user: User, code: str, now: float | None = None) -> bool:
    """Whether `code` is a good authenticator code or an unused recovery code. Uses it up."""
    code = code.strip()
    secret = _secret(user)
    if secret is not None:
        step = totp.verify(
            secret, code, now if now is not None else time.time(), user.totp_last_step
        )
        if step is not None:
            user.totp_last_step = step
            session.commit()
            return True
    hashed = hash_token(code.lower())
    if hashed in user.recovery_codes:
        user.recovery_codes = [h for h in user.recovery_codes if h != hashed]
        session.commit()
        return True
    return False


def disable(session: Session, user: User, password: str, code: str) -> None:
    if not verify_password(user.password_hash, password):
        raise InvalidCodeError("Password is incorrect.", code="wrong_password")
    if not is_enabled(user) or not check_code(session, user, code):
        raise InvalidCodeError("That code is not right.")
    clear(session, user)


def clear(session: Session, user: User) -> None:
    """Remove two-factor sign-in (also used by the server-side reset script)."""
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    user.recovery_codes = []
    session.commit()


def new_recovery_codes(session: Session, user: User, code: str) -> list[str]:
    if not is_enabled(user) or not check_code(session, user, code):
        raise InvalidCodeError("That code is not right.")
    codes = _new_recovery_codes(user)
    session.commit()
    return codes
