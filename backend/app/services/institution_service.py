"""Seat logins for an institution.

One seat = one account with its own login ID and password, so access is per person. The owner
cannot create more active seats than the plan allows; a seat account can only be signed in on one
device at a time (enforced in auth_service.login). Passwords are shown once, when made or reset.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models.base import ensure_utc, utcnow
from app.models.billing import Institution, InstitutionSeat
from app.models.user import Role, User, UserRole, UserSession
from app.services import auth_service
from app.services.billing_service import _active_seat_count, _live, institution_subscription

_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes
PASSWORD_LENGTH = 12
MAX_NAMES_PER_CALL = 20


def make_password() -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))


@dataclass(frozen=True)
class NewSeat:
    seat_id: uuid.UUID
    login_id: str
    name: str
    password: str


@dataclass(frozen=True)
class SeatRow:
    seat_id: uuid.UUID
    login_id: str
    name: str
    active: bool
    last_login_at: datetime | None


@dataclass(frozen=True)
class Overview:
    institution: Institution
    plan_code: str | None
    seats_allowed: int
    seats_used: int
    ends_at: datetime | None
    subscription_live: bool
    seats: list[SeatRow]


def get_owned(session: Session, owner: User, *, lock: bool = False) -> Institution:
    stmt = select(Institution).where(Institution.owner_id == owner.id)
    if lock:
        stmt = stmt.with_for_update()
    inst = session.scalar(stmt)
    if inst is None:
        raise NotFoundError("You do not manage an institution yet.", code="no_institution")
    return inst


def _seat_of(
    session: Session, inst: Institution, seat_id: uuid.UUID
) -> tuple[InstitutionSeat, User]:
    seat = session.get(InstitutionSeat, seat_id)
    if seat is None or seat.institution_id != inst.id:
        raise NotFoundError("Login not found.", code="seat_not_found")
    user = session.get(User, seat.user_id)
    assert user is not None
    return seat, user


def overview(session: Session, owner: User) -> Overview:
    inst = get_owned(session, owner)
    sub = institution_subscription(session, inst.id)
    rows = session.execute(
        select(InstitutionSeat, User)
        .join(User, User.id == InstitutionSeat.user_id)
        .where(InstitutionSeat.institution_id == inst.id)
        .order_by(User.login_id)
    ).all()
    last_login: dict[uuid.UUID, datetime] = {
        uid: seen
        for uid, seen in session.execute(
            select(UserSession.user_id, func.max(UserSession.created_at))
            .where(UserSession.user_id.in_([u.id for _, u in rows]))
            .group_by(UserSession.user_id)
        )
        if seen is not None
    }
    seats = [
        SeatRow(
            seat_id=s.id,
            login_id=u.login_id or "",
            name=u.display_name,
            active=u.is_active,
            last_login_at=ensure_utc(last_login[u.id]) if u.id in last_login else None,
        )
        for s, u in rows
    ]
    return Overview(
        institution=inst,
        plan_code=sub.plan_code if sub else None,
        seats_allowed=(sub.seats or 0) if sub else 0,
        seats_used=sum(1 for r in seats if r.active),
        ends_at=ensure_utc(sub.current_period_end) if sub else None,
        subscription_live=_live(sub, utcnow()),
        seats=seats,
    )


def _require_live_subscription(session: Session, inst: Institution) -> int:
    """Seats allowed by the running plan, or an error when the plan has ended."""
    sub = institution_subscription(session, inst.id)
    if not _live(sub, utcnow()) or sub is None:
        raise ForbiddenError(
            "Your institution's plan has ended. Renew it to manage logins.",
            code="institution_expired",
        )
    return sub.seats or 0


def create_seats(session: Session, owner: User, names: list[str]) -> list[NewSeat]:
    inst = get_owned(session, owner, lock=True)  # serialises concurrent creates
    allowed = _require_live_subscription(session, inst)
    cleaned = [" ".join(n.split())[:100] for n in names]
    cleaned = [n for n in cleaned if n]
    if not cleaned or len(cleaned) > MAX_NAMES_PER_CALL:
        raise ConflictError(
            f"Add between 1 and {MAX_NAMES_PER_CALL} names at a time.", code="invalid_names"
        )
    free = allowed - _active_seat_count(session, inst.id)
    if len(cleaned) > free:
        raise ConflictError(
            f"Your plan has {max(free, 0)} free login(s) and you asked for {len(cleaned)}. "
            "Close a login you no longer need, or move to a bigger plan when this one ends.",
            code="seat_limit_reached",
            details={"free": max(free, 0), "allowed": allowed},
        )
    now = utcnow()
    created: list[NewSeat] = []
    for name in cleaned:
        inst.seat_counter += 1
        login_id = f"{inst.code}-{inst.seat_counter:03d}"
        password = make_password()
        user = User(
            email=None,
            login_id=login_id,
            password_hash=hash_password(password),
            display_name=name,
            email_verified_at=now,  # there is no email to verify
            roles=[UserRole(role=Role.LEARNER)],
        )
        session.add(user)
        session.flush()
        seat = InstitutionSeat(institution_id=inst.id, user_id=user.id)
        session.add(seat)
        session.flush()
        created.append(NewSeat(seat.id, login_id, name, password))
    session.commit()
    return created


def reset_password(session: Session, owner: User, seat_id: uuid.UUID) -> NewSeat:
    inst = get_owned(session, owner)
    _, user = _seat_of(session, inst, seat_id)
    password = make_password()
    user.password_hash = hash_password(password)
    auth_service.revoke_all_sessions(session, user.id)
    session.commit()
    return NewSeat(seat_id, user.login_id or "", user.display_name, password)


def set_active(session: Session, owner: User, seat_id: uuid.UUID, active: bool) -> None:
    inst = get_owned(session, owner, lock=True)
    _, user = _seat_of(session, inst, seat_id)
    if active and not user.is_active:
        allowed = _require_live_subscription(session, inst)
        if _active_seat_count(session, inst.id) >= allowed:
            raise ConflictError(
                "All the logins in your plan are in use. Close another one first.",
                code="seat_limit_reached",
                details={"free": 0, "allowed": allowed},
            )
    user.is_active = active
    if not active:
        auth_service.revoke_all_sessions(session, user.id)
    session.commit()
