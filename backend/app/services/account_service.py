"""What a person can do with their own account: export it, change its email, delete it.

Deleting erases the personal data but KEEPS the row, with name and email blanked. Reason: payment
records must be kept for tax and accounting law, and they point at the user row. What is kept
afterwards is the payment (plan, months, amount, date, reference) and nothing that says who it was.
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, inspect, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.core.security import hash_password, new_token, verify_password
from app.models.base import utcnow
from app.models.billing import InstitutionSeat, SavedCard, Subscription
from app.models.exercise_attempt import ExerciseAttempt
from app.models.job import Job
from app.models.library import LibraryItem
from app.models.practice_attempt import PracticeAttempt
from app.models.user import OneTimeToken, Role, User, UserRole, UserSession
from app.services import auth_service, billing_service, two_factor_service
from app.services.email import EmailMessage, EmailSender
from app.services.file_store import FileStore

logger = logging.getLogger("app.account")
EMAIL_CHANGE_TTL = timedelta(hours=2)
DELETED_NAME = "Deleted account"


# ---------------------------------------------------------------- export


def _plain(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "value"):  # enums
        return value.value
    return value


def _rows(
    session: Session, model: Any, user_id: uuid.UUID, order: Any, limit: int = 50_000
) -> list[dict[str, Any]]:
    """Every column of the person's rows, except the owner id (it is their own export)."""
    cols = [c.key for c in inspect(model).columns if c.key != "user_id"]
    owner: Any = model.user_id
    out = session.scalars(select(model).where(owner == user_id).order_by(order).limit(limit))
    return [{c: _plain(getattr(r, c)) for c in cols} for r in out]


def export_data(session: Session, user: User) -> dict[str, Any]:
    """Everything we hold about this person, as plain JSON (GDPR/NDPA "right of access").

    Saved MIDI files are not inlined (they can be large): download them from My Library.
    Secrets (password hash, two-factor key, session tokens) are never included.
    """
    inst = billing_service.owned_institution(session, user)
    institution: dict[str, Any] | None = None
    if inst is not None:
        seats = session.execute(
            select(InstitutionSeat, User)
            .join(User, User.id == InstitutionSeat.user_id)
            .where(InstitutionSeat.institution_id == inst.id)
        ).all()
        institution = {
            "name": inst.name,
            "login_prefix": inst.code,
            "logins": [
                {"name": u.display_name, "login_id": u.login_id, "active": u.is_active}
                for _, u in seats
            ],
        }
    sub = session.scalar(select(Subscription).where(Subscription.user_id == user.id))
    return {
        "exported_at": utcnow().isoformat(),
        "profile": {
            "id": str(user.id),
            "email": user.email,
            "login_id": user.login_id,
            "display_name": user.display_name,
            "roles": sorted(r.value for r in user.role_names),
            "created_at": _plain(user.created_at),
            "email_verified_at": _plain(user.email_verified_at),
            "plan_reminder_emails": user.reminder_emails,
            "two_factor_enabled": two_factor_service.is_enabled(user),
        },
        "subscription": (
            {"plan": sub.plan_code, "access_until": _plain(sub.current_period_end)} if sub else None
        ),
        "payments": [
            {
                "reference": p.reference,
                "plan": p.plan_code,
                "months": p.months,
                "amount_naira": p.amount_kobo / 100,
                "currency": p.currency,
                "status": p.status,
                "created_at": _plain(p.created_at),
                "paid_at": _plain(p.paid_at),
                "institution_name": p.institution_name,
            }
            for p in billing_service.list_payments(session, user, limit=1000)
        ],
        "institution_managed": institution,
        "library": [
            {k: v for k, v in row.items() if k != "id"}
            for row in _rows(session, LibraryItem, user.id, LibraryItem.created_at)
        ],
        "sign_ins": [
            {
                "created_at": _plain(s.created_at),
                "last_seen_at": _plain(s.last_seen_at),
                "ip_address": s.ip,
                "device": s.user_agent,
            }
            for s in session.scalars(
                select(UserSession)
                .where(UserSession.user_id == user.id)
                .order_by(UserSession.created_at.desc())
                .limit(200)
            )
        ],
        "practice_attempts": _rows(session, PracticeAttempt, user.id, PracticeAttempt.created_at),
        "theory_answers": _rows(session, ExerciseAttempt, user.id, ExerciseAttempt.created_at),
    }


# ---------------------------------------------------------------- delete


def delete_account(
    session: Session,
    store: FileStore,
    user: User,
    *,
    password: str,
    otp: str | None,
    sender: EmailSender,
) -> None:
    if user.login_id is not None:
        raise ForbiddenError(
            "Your institution manages this login. Ask them to close it.", code="seat_managed"
        )
    if not verify_password(user.password_hash, password):
        raise auth_service.InvalidCredentialsError("Password is incorrect.", code="wrong_password")
    if two_factor_service.is_enabled(user) and not (
        otp and two_factor_service.check_code(session, user, otp)
    ):
        raise two_factor_service.InvalidCodeError("Enter a current two-factor code to continue.")

    if Role.ADMIN in user.role_names:
        others = session.scalar(
            select(UserRole.user_id)
            .join(User, User.id == UserRole.user_id)
            .where(UserRole.role == Role.ADMIN, User.is_active.is_(True), User.id != user.id)
            .limit(1)
        )
        if others is None:
            raise ConflictError(
                "You are the only administrator. Make someone else an administrator first.",
                code="last_admin",
            )

    now = utcnow()
    inst = billing_service.owned_institution(session, user)
    if inst is not None:
        sub = billing_service.institution_subscription(session, inst.id)
        if billing_service._live(sub, now):
            raise ConflictError(
                "You manage an institution whose plan is still running, so its people would lose "
                "access. Wait for the plan to end, or contact support to hand it over.",
                code="institution_active",
            )
        for _, seat_user in session.execute(
            select(InstitutionSeat, User)
            .join(User, User.id == InstitutionSeat.user_id)
            .where(InstitutionSeat.institution_id == inst.id)
        ):
            seat_user.is_active = False
            auth_service.revoke_all_sessions(session, seat_user.id)
        inst.is_active = False

    old_email = user.email
    for key in session.scalars(select(LibraryItem.id).where(LibraryItem.user_id == user.id)):
        try:
            store.delete(store.key(user.id, key))
        except OSError:  # a leftover file is harmless and is found by scripts.cleanup_storage
            logger.warning("Could not remove a saved file for a deleted account")
    for model in (LibraryItem, PracticeAttempt, ExerciseAttempt, Job, UserSession, OneTimeToken):
        session.execute(delete(model).where(model.user_id == user.id))
    session.execute(delete(Subscription).where(Subscription.user_id == user.id))
    session.execute(delete(SavedCard).where(SavedCard.user_id == user.id))
    session.execute(delete(UserRole).where(UserRole.user_id == user.id))
    session.flush()
    session.expire(user, ["roles"])

    user.email = None
    user.login_id = None
    user.display_name = DELETED_NAME
    user.password_hash = hash_password(new_token())  # nobody knows it
    user.is_active = False
    user.reminder_emails = False
    user.email_verified_at = None
    user.deleted_at = now
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    user.recovery_codes = []
    session.add(UserRole(user_id=user.id, role=Role.LEARNER))
    session.commit()

    if old_email:
        try:
            sender.send(
                EmailMessage(
                    to=old_email,
                    subject="Your account has been deleted",
                    body=(
                        "Your account and the data attached to it have been deleted.\n\n"
                        "We keep only the payment records the law requires, without your name "
                        "or email.\n"
                        "If you did not do this, contact support straight away."
                    ),
                )
            )
        except AppError:
            logger.warning("Could not send the account-deleted email")


# ---------------------------------------------------------------- change email


def request_email_change(
    session: Session,
    user: User,
    *,
    new_email: str,
    password: str,
    settings: Settings,
    sender: EmailSender,
) -> None:
    """Send a link to the NEW address. The email changes only when the link is opened.

    The reply is the same whether or not that address is already registered, so this cannot be
    used to find out who has an account.
    """
    if user.login_id is not None or user.email is None:
        raise ForbiddenError("This login has no email to change.", code="seat_managed")
    if not verify_password(user.password_hash, password):
        raise auth_service.InvalidCredentialsError("Password is incorrect.", code="wrong_password")
    new = auth_service.normalize_email(new_email)
    if new == user.email:
        raise ConflictError("That is already your email.", code="same_email")
    taken = session.scalar(select(User.id).where(User.email == new)) is not None
    if taken:
        auth_service._notify_existing_account(sender, new, settings)
        return
    raw = auth_service._issue_token(
        session, user, auth_service.PURPOSE_EMAIL_CHANGE, EMAIL_CHANGE_TTL, payload=new
    )
    session.commit()
    link = auth_service._web_link(settings, "/confirm-email-change", raw)
    sender.send(
        EmailMessage(
            to=new,
            subject="Confirm your new email",
            body=(
                f"Open this link to use this address for your account at "
                f"{settings.public_web_url}:\n{link}\n\n"
                "It works once and expires in 2 hours. "
                "If you did not ask for this, ignore this email."
            ),
        )
    )


def confirm_email_change(
    session: Session, raw_token: str, *, settings: Settings, sender: EmailSender
) -> None:
    token = auth_service._consume_token(session, raw_token, auth_service.PURPOSE_EMAIL_CHANGE)
    user = session.get(User, token.user_id)
    new = token.payload
    if user is None or not user.is_active or user.deleted_at is not None or not new:
        raise auth_service.InvalidTokenError("This link is invalid or has expired.")
    if session.scalar(select(User.id).where(User.email == new, User.id != user.id)) is not None:
        raise ConflictError("That email is now used by another account.", code="email_taken")
    old = user.email
    user.email = new
    user.email_verified_at = utcnow()  # opening the link proves they own it
    # Links sent to the old address must stop working, and every device signs in again.
    session.execute(
        update(OneTimeToken)
        .where(OneTimeToken.user_id == user.id, OneTimeToken.used_at.is_(None))
        .values(used_at=utcnow())
    )
    auth_service.revoke_all_sessions(session, user.id)
    session.commit()
    if old:
        try:
            sender.send(
                EmailMessage(
                    to=old,
                    subject="Your email was changed",
                    body=(
                        f"The email on your account was changed to {new}.\n"
                        "If you did not do this, contact support straight away."
                    ),
                )
            )
        except AppError:
            logger.warning("Could not send the email-changed notice")
