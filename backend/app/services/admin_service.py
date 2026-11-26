"""Administrator tools for people's accounts, and the log of what administrators did.

Every change an administrator makes to access, roles or money is written to `admin_actions`
(who, what, to whom, details, when). The log is add-only.
"""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.models.audit import AdminAction
from app.models.base import utcnow
from app.models.billing import InstitutionSeat, Payment
from app.models.library import LibraryItem
from app.models.user import Role, User, UserRole, UserSession
from app.services import auth_service, billing_service, library_service, two_factor_service

MAX_PAGE = 100


def record(
    session: Session,
    actor: User | None,
    action: str,
    target: User | None = None,
    **detail: Any,
) -> None:
    """Add a line to the log. The caller commits, so the action and its log line save together."""
    label = ""
    if target is not None:
        label = target.email or target.login_id or target.display_name
    session.add(
        AdminAction(
            actor_id=actor.id if actor else None,
            actor_email=(actor.email or actor.display_name) if actor else "system (Paystack)",
            action=action,
            target_user_id=target.id if target else None,
            target_label=label[:320],
            detail=detail,
        )
    )


def get_target(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("No such account.", code="user_not_found")
    return user


def kind_of(session: Session, user: User) -> str:
    if billing_service.is_seat(session, user):
        return "seat"
    if billing_service.owned_institution(session, user) is not None:
        return "institution_owner"
    return "individual"


def list_users(
    session: Session, *, q: str | None, role: str | None, limit: int, offset: int
) -> tuple[list[User], int]:
    stmt = select(User).where(User.deleted_at.is_(None))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(like),
                func.lower(User.login_id).like(like),
                func.lower(User.display_name).like(like),
            )
        )
    if role in {r.value for r in Role}:
        stmt = stmt.where(User.id.in_(select(UserRole.user_id).where(UserRole.role == Role(role))))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(
        stmt.order_by(User.created_at.desc())
        .limit(max(1, min(limit, MAX_PAGE)))
        .offset(max(0, offset))
    )
    return list(rows), int(total)


def detail(session: Session, target: User, settings: Settings) -> dict[str, Any]:
    ent = billing_service.resolve_entitlement(session, target, settings, start_trial=False)
    inst = billing_service.owned_institution(session, target)
    seat_of = session.execute(
        select(InstitutionSeat.institution_id).where(InstitutionSeat.user_id == target.id)
    ).scalar_one_or_none()
    count, size = library_service.usage(session, target)
    return {
        "user": target,
        "kind": kind_of(session, target),
        "entitlement": ent,
        "owns_institution": inst,
        "seat_of": seat_of,
        "library": (count, size),
        "payments": list(
            session.scalars(
                select(Payment)
                .where(Payment.user_id == target.id)
                .order_by(Payment.created_at.desc())
                .limit(10)
            )
        ),
        "active_sessions": session.scalar(
            select(func.count())
            .select_from(UserSession)
            .where(
                UserSession.user_id == target.id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > utcnow(),
            )
        )
        or 0,
        "library_items": session.scalar(
            select(func.count()).select_from(LibraryItem).where(LibraryItem.user_id == target.id)
        )
        or 0,
    }


def set_active(session: Session, actor: User, target: User, active: bool) -> None:
    if target.id == actor.id:
        raise ConflictError("You cannot close your own account here.", code="self_action")
    if billing_service.is_seat(session, target):
        raise ConflictError(
            "This login belongs to an institution; its manager opens and closes it.",
            code="seat_managed",
        )
    target.is_active = active
    if not active:
        auth_service.revoke_all_sessions(session, target.id)
    record(session, actor, "account_reopened" if active else "account_closed", target)
    session.commit()


def sign_out(session: Session, actor: User, target: User) -> None:
    auth_service.revoke_all_sessions(session, target.id)
    record(session, actor, "signed_out_everywhere", target)
    session.commit()


def set_role(session: Session, actor: User, target: User, role: Role, grant: bool) -> None:
    if role is Role.LEARNER:
        raise ConflictError("Everyone keeps the learner role.", code="invalid_role")
    if target.id == actor.id:
        raise ConflictError("You cannot change your own roles.", code="self_action")
    if billing_service.is_seat(session, target) or target.email is None:
        raise ForbiddenError("Institution logins cannot be given staff roles.", code="seat_managed")
    has = role in target.role_names
    if grant and not has:
        if target.email_verified_at is None or not target.is_active:
            raise ConflictError("That account is not active and verified.", code="not_eligible")
        target.roles.append(UserRole(role=role))
    elif not grant and has:
        target.roles = [r for r in target.roles if r.role is not role]
        auth_service.revoke_all_sessions(session, target.id)  # sign in again with the new rights
    else:
        return
    record(session, actor, "role_granted" if grant else "role_removed", target, role=role.value)
    session.commit()


def reset_two_factor(session: Session, actor: User, target: User) -> None:
    """For someone who lost their phone. Not allowed on administrators: for them it needs the
    server (`scripts/make_admin.py --reset-2fa`), so one admin cannot quietly lift another's."""
    if Role.ADMIN in target.role_names:
        raise ForbiddenError(
            "Two-factor for an administrator is reset on the server, not here.",
            code="admin_two_factor",
        )
    if not two_factor_service.is_enabled(target):
        raise ConflictError("Two-factor sign-in is not on for this account.", code="not_enabled")
    two_factor_service.clear(session, target)
    auth_service.revoke_all_sessions(session, target.id)
    record(session, actor, "two_factor_reset", target)
    session.commit()


def audit_log(
    session: Session, *, limit: int = 100, target_id: uuid.UUID | None = None
) -> list[AdminAction]:
    stmt = select(AdminAction).order_by(AdminAction.created_at.desc())
    if target_id is not None:
        stmt = stmt.where(AdminAction.target_user_id == target_id)
    return list(session.scalars(stmt.limit(max(1, min(limit, 500)))))
