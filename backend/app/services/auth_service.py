"""Accounts, sessions and one-time tokens.

Design notes (see docs/adr/0003-authentication.md):
- Responses never reveal whether an email is registered (register, login, reset request).
- Session cookies and one-time tokens are random; only their SHA-256 hashes are stored.
- Changing or resetting a password revokes other sessions.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.security import (
    burn_password_check,
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    verify_password,
)
from app.models.base import ensure_utc, utcnow
from app.models.user import OneTimeToken, Role, User, UserRole, UserSession
from app.services import two_factor_service
from app.services.email import EmailMessage, EmailSender

logger = logging.getLogger("app.auth")

PURPOSE_VERIFY = "verify_email"
PURPOSE_RESET = "password_reset"
PURPOSE_EMAIL_CHANGE = "email_change"
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)
MIN_PASSWORD = 10
MAX_PASSWORD = 128
_COMMON = {
    "password",
    "password1",
    "password123",
    "1234567890",
    "12345678910",
    "qwertyuiop",
    "iloveyou123",
    "letmein1234",
    "welcome1234",
    "pianopiano",
}


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"


class EmailNotVerifiedError(AppError):
    status_code = 403
    code = "email_not_verified"


class InvalidTokenError(AppError):
    status_code = 400
    code = "invalid_token"


class WeakPasswordError(AppError):
    status_code = 422
    code = "weak_password"


@dataclass(frozen=True)
class AuthContext:
    user: User
    session_id: uuid.UUID


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_identifier(identifier: str) -> str:
    """Emails are lowercase; institution login IDs (no "@") are uppercase."""
    value = identifier.strip()
    return value.lower() if "@" in value else value.upper()


def validate_password(password: str, email: str | None) -> None:
    """Length-based policy (NIST 800-63B style). Does not check breached-password lists."""
    if len(password) < MIN_PASSWORD:
        raise WeakPasswordError(f"Use at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise WeakPasswordError(f"Use at most {MAX_PASSWORD} characters.")
    lowered = password.lower()
    if lowered == normalize_email(email or "") or lowered in _COMMON:
        raise WeakPasswordError("That password is too easy to guess. Choose a different one.")


def _issue_token(
    session: Session, user: User, purpose: str, ttl: timedelta, payload: str | None = None
) -> str:
    raw = new_token()
    session.add(
        OneTimeToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=utcnow() + ttl,
            payload=payload,
        )
    )
    return raw


def _consume_token(session: Session, raw: str, purpose: str) -> OneTimeToken:
    row = session.scalar(
        select(OneTimeToken).where(
            OneTimeToken.token_hash == hash_token(raw), OneTimeToken.purpose == purpose
        )
    )
    if row is None or row.used_at is not None or ensure_utc(row.expires_at) <= utcnow():
        raise InvalidTokenError("This link is invalid or has expired. Request a new one.")
    row.used_at = utcnow()
    return row


def _web_link(settings: Settings, path: str, token: str) -> str:
    return f"{settings.public_web_url.rstrip('/')}{path}?token={token}"


def register(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    sender: EmailSender,
    settings: Settings,
) -> None:
    """Always returns normally for a well-formed request, whether or not the email is taken."""
    email = normalize_email(email)
    validate_password(password, email)
    password_hash = hash_password(password)  # hashed first so both paths cost the same
    if session.scalar(select(User).where(User.email == email)) is not None:
        _notify_existing_account(sender, email, settings)
        return
    user = User(
        email=email,
        password_hash=password_hash,
        display_name=display_name,
        roles=[UserRole(role=Role.LEARNER)],
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:  # concurrent registration with the same email
        session.rollback()
        _notify_existing_account(sender, email, settings)
        return
    raw = _issue_token(session, user, PURPOSE_VERIFY, VERIFY_TTL)
    session.commit()
    sender.send(
        EmailMessage(
            to=email,
            subject="Verify your email",
            body=(
                f"Hi {display_name},\n\nConfirm your email to activate your account:\n"
                f"{_web_link(settings, '/verify-email', raw)}\n\n"
                "The link works once and expires in 24 hours.\n"
                "If you did not sign up, ignore this email."
            ),
        )
    )


def _notify_existing_account(sender: EmailSender, email: str, settings: Settings) -> None:
    sender.send(
        EmailMessage(
            to=email,
            subject="Sign-up attempt for your account",
            body=(
                "Someone tried to create an account with this email, but one already exists.\n"
                "If it was you, sign in or reset your password at "
                f"{settings.public_web_url}/login.\n"
                "If not, you can ignore this email."
            ),
        )
    )


def verify_email(session: Session, raw_token: str) -> None:
    token = _consume_token(session, raw_token, PURPOSE_VERIFY)
    user = session.get(User, token.user_id)
    if user is None:
        raise InvalidTokenError("This link is invalid or has expired. Request a new one.")
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    session.commit()


def login(
    session: Session,
    *,
    identifier: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
    settings: Settings,
    otp: str | None = None,
) -> tuple[User, str]:
    """Sign in with an email or, for institution seats, a login ID. `otp` is the two-factor code."""
    identifier = normalize_identifier(identifier)
    column = User.email if "@" in identifier else User.login_id
    user = session.scalar(select(User).where(column == identifier))
    if user is None:
        burn_password_check(password)
        raise InvalidCredentialsError("Email or password is incorrect.")
    if not verify_password(user.password_hash, password) or not user.is_active:
        raise InvalidCredentialsError("Email or password is incorrect.")
    if user.email_verified_at is None:
        raise EmailNotVerifiedError("Verify your email before signing in. Check your inbox.")
    if two_factor_service.is_enabled(user):
        if not otp:
            raise two_factor_service.TwoFactorRequiredError(
                "Enter the 6-digit code from your authenticator app."
            )
        if not two_factor_service.check_code(session, user, otp):
            raise two_factor_service.InvalidCodeError("That code is not right or was already used.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    if user.login_id is not None:
        # Institution seats are one person each: signing in here signs out any other device, so
        # a shared password cannot be used by two people at once.
        revoke_all_sessions(session, user.id)
    raw = new_token()
    now = utcnow()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(raw),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=settings.session_ttl_days),
            user_agent=(user_agent or "")[:255] or None,
            ip=ip,
        )
    )
    session.commit()
    return user, raw


def authenticate_session(
    session: Session, raw_token: str, settings: Settings
) -> AuthContext | None:
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw_token)))
    if row is None or row.revoked_at is not None:
        return None
    now = utcnow()
    last_seen = ensure_utc(row.last_seen_at)
    if ensure_utc(row.expires_at) <= now:
        return None
    if now - last_seen > timedelta(days=settings.session_idle_days):
        return None
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    if now - last_seen > timedelta(seconds=60):  # avoid a write on every request
        row.last_seen_at = now
        session.commit()
    return AuthContext(user=user, session_id=row.id)


def revoke_session(session: Session, raw_token: str) -> None:
    session.execute(
        update(UserSession)
        .where(UserSession.token_hash == hash_token(raw_token), UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    session.commit()


def revoke_all_sessions(
    session: Session, user_id: uuid.UUID, *, except_session_id: uuid.UUID | None = None
) -> None:
    stmt = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if except_session_id is not None:
        stmt = stmt.where(UserSession.id != except_session_id)
    session.execute(stmt.values(revoked_at=utcnow()))


def request_password_reset(
    session: Session, *, email: str, sender: EmailSender, settings: Settings
) -> None:
    """Silent when the account does not exist or is inactive."""
    user = session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None or not user.is_active:
        return
    assert user.email is not None  # looked up by email
    session.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == user.id,
            OneTimeToken.purpose == PURPOSE_RESET,
            OneTimeToken.used_at.is_(None),
        )
        .values(used_at=utcnow())
    )
    raw = _issue_token(session, user, PURPOSE_RESET, RESET_TTL)
    session.commit()
    sender.send(
        EmailMessage(
            to=user.email,
            subject="Reset your password",
            body=(
                "Use this link to choose a new password:\n"
                f"{_web_link(settings, '/reset-password', raw)}\n\n"
                "It works once and expires in 1 hour.\n"
                "If you did not ask for this, ignore this email."
            ),
        )
    )


def confirm_password_reset(session: Session, *, raw_token: str, new_password: str) -> None:
    token = _consume_token(session, raw_token, PURPOSE_RESET)
    user = session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("This link is invalid or has expired. Request a new one.")
    validate_password(new_password, user.email)
    user.password_hash = hash_password(new_password)
    if user.email_verified_at is None:  # receiving the email proves ownership
        user.email_verified_at = utcnow()
    revoke_all_sessions(session, user.id)
    session.commit()


def change_password(
    session: Session,
    *,
    ctx: AuthContext,
    current_password: str,
    new_password: str,
) -> None:
    user = ctx.user
    if not verify_password(user.password_hash, current_password):
        raise InvalidCredentialsError("Current password is incorrect.", code="wrong_password")
    validate_password(new_password, user.email)
    user.password_hash = hash_password(new_password)
    revoke_all_sessions(session, user.id, except_session_id=ctx.session_id)
    session.commit()


def update_display_name(session: Session, user: User, display_name: str) -> User:
    user.display_name = display_name
    session.commit()
    return user


def deactivate_account(session: Session, *, user: User, password: str) -> None:
    if user.login_id is not None:
        raise ForbiddenError(
            "Your institution manages this login. Ask them to close it.", code="seat_managed"
        )
    if not verify_password(user.password_hash, password):
        raise InvalidCredentialsError("Password is incorrect.", code="wrong_password")
    user.is_active = False
    revoke_all_sessions(session, user.id)
    session.commit()


def get_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found", code="user_not_found")
    return user
