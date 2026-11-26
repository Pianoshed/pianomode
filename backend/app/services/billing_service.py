"""Who may use the app, and how a payment becomes access.

Rules (docs/adr/0011-subscriptions.md):
- Access = staff role, OR an institution seat whose institution is paid up, OR a paid individual
  period, OR an unexpired trial.
- Every payment is a prepaid block of `months` x 30 days. Paying again before the end adds to the
  end date. Nothing renews or charges by itself UNLESS the person ticked "renew automatically"
  and PIANO_AUTO_RENEWAL_ENABLED is on (app/services/renewal_service.py; ADR 0016).
- The price is computed here from plans.py, never taken from the browser. Access is only granted
  after Paystack confirms the transaction succeeded for exactly the amount we asked for.
- Settling a payment is idempotent: the webhook and the return page may both fire.
"""

import logging
import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.models.base import ensure_utc, utcnow
from app.models.billing import Institution, InstitutionSeat, Payment, SavedCard, Subscription
from app.models.user import Role, User
from app.services.email import EmailMessage, EmailSender
from app.services.paystack import CardAuthorization, PaystackClient, PaystackError
from app.services.plans import CURRENCY, MAX_MONTHS, TRIAL_PLAN, Plan, get_plan

logger = logging.getLogger("app.billing")

Source = Literal["staff", "individual", "trial", "institution", "none"]
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


class InvalidPlanError(AppError):
    status_code = 422
    code = "invalid_plan"


@dataclass(frozen=True)
class Entitlement:
    has_access: bool
    source: Source
    plan_code: str | None = None
    ends_at: datetime | None = None
    institution_name: str | None = None
    # Why there is no access: "expired" (own plan), "institution_expired" (a seat's institution),
    # "seat_closed", or "none".
    reason: str = "ok"


def is_seat(session: Session, user: User) -> bool:
    return (
        session.scalar(select(InstitutionSeat.id).where(InstitutionSeat.user_id == user.id))
        is not None
    )


def owned_institution(session: Session, user: User) -> Institution | None:
    return session.scalar(select(Institution).where(Institution.owner_id == user.id))


def _subscription_for_user(session: Session, user_id: uuid.UUID) -> Subscription | None:
    return session.scalar(select(Subscription).where(Subscription.user_id == user_id))


def institution_subscription(session: Session, institution_id: uuid.UUID) -> Subscription | None:
    return session.scalar(select(Subscription).where(Subscription.institution_id == institution_id))


def _live(sub: Subscription | None, now: datetime) -> bool:
    return sub is not None and ensure_utc(sub.current_period_end) > now


def _start_trial(
    session: Session, user: User, settings: Settings, now: datetime
) -> Subscription | None:
    if settings.trial_days <= 0:
        return None
    sub = Subscription(
        user_id=user.id,
        plan_code=TRIAL_PLAN,
        current_period_end=now + timedelta(days=settings.trial_days),
    )
    session.add(sub)
    try:
        session.commit()
    except IntegrityError:  # two first requests at once; the other one made it
        session.rollback()
        return _subscription_for_user(session, user.id)
    return sub


def resolve_entitlement(
    session: Session,
    user: User,
    settings: Settings,
    now: datetime | None = None,
    *,
    start_trial: bool = True,
) -> Entitlement:
    now = now or utcnow()
    if user.role_names & {Role.ADMIN, Role.EDUCATOR}:
        return Entitlement(True, "staff")

    seat = session.scalar(select(InstitutionSeat).where(InstitutionSeat.user_id == user.id))
    if seat is not None:
        inst = session.get(Institution, seat.institution_id)
        sub = institution_subscription(session, seat.institution_id)
        name = inst.name if inst else None
        if inst is None or not inst.is_active:
            return Entitlement(False, "none", institution_name=name, reason="seat_closed")
        if _live(sub, now):
            assert sub is not None
            return Entitlement(
                True, "institution", sub.plan_code, ensure_utc(sub.current_period_end), name
            )
        return Entitlement(
            False,
            "none",
            sub.plan_code if sub else None,
            ensure_utc(sub.current_period_end) if sub else None,
            name,
            reason="institution_expired",
        )

    sub = _subscription_for_user(session, user.id)
    if sub is None and start_trial:
        sub = _start_trial(session, user, settings, now)
    if sub is None:
        return Entitlement(False, "none", reason="none")
    source: Source = "trial" if sub.plan_code == TRIAL_PLAN else "individual"
    ends = ensure_utc(sub.current_period_end)
    if ends > now:
        return Entitlement(True, source, sub.plan_code, ends)
    return Entitlement(False, "none", sub.plan_code, ends, reason="expired")


# ---------------------------------------------------------------- checkout


@dataclass(frozen=True)
class Checkout:
    reference: str
    authorization_url: str
    amount_kobo: int


def _clean_name(name: str | None) -> str | None:
    cleaned = " ".join((name or "").split())
    return cleaned[:120] or None


def create_checkout(
    session: Session,
    *,
    user: User,
    plan_code: str,
    months: int,
    institution_name: str | None,
    client: PaystackClient,
    settings: Settings,
    save_card: bool = False,
) -> Checkout:
    if is_seat(session, user):
        raise ForbiddenError(
            "Your access comes from your institution. Ask its manager to renew.",
            code="seat_cannot_purchase",
        )
    if user.email is None:
        raise ForbiddenError("This account cannot make payments.", code="seat_cannot_purchase")
    plan = get_plan(plan_code)
    if plan is None:
        raise InvalidPlanError("That plan does not exist.")
    if not 1 <= months <= MAX_MONTHS:
        raise InvalidPlanError(f"Choose between 1 and {MAX_MONTHS} months.")

    institution_id: uuid.UUID | None = None
    name: str | None = None
    if plan.kind == "institution":
        inst = owned_institution(session, user)
        if inst is None:
            name = _clean_name(institution_name)
            if name is None:
                raise InvalidPlanError(
                    "Enter your institution's name.", code="institution_name_required"
                )
        else:
            institution_id = inst.id
            name = inst.name
            sub = institution_subscription(session, inst.id)
            cur = get_plan(sub.plan_code) if sub else None
            if (
                sub is not None
                and cur is not None
                and cur.code != plan.code
                and _live(sub, utcnow())
                and (plan.seats or 0) > (cur.seats or 0)
            ):
                # A bigger plan while one is running: pay the difference for the rest of the period.
                return create_upgrade_checkout(
                    session, user=user, plan_code=plan.code, client=client, settings=settings
                )
            _check_plan_change(session, inst, plan, utcnow())

    amount = plan.monthly_kobo * months
    payment = Payment(
        reference=f"pp_{secrets.token_hex(14)}",
        user_id=user.id,
        plan_code=plan.code,
        months=months,
        amount_kobo=amount,
        currency=CURRENCY,
        institution_name=name,
        institution_id=institution_id,
        save_card=save_card and settings.auto_renewal_enabled,
    )
    return _start_payment(session, payment, user, client, settings)


def _start_payment(
    session: Session, payment: Payment, user: User, client: PaystackClient, settings: Settings
) -> Checkout:
    """Save the pending payment, then ask Paystack for its checkout page."""
    assert user.email is not None
    session.add(payment)
    session.commit()
    try:
        checkout = client.initialize(
            email=user.email,
            amount_kobo=payment.amount_kobo,
            reference=payment.reference,
            callback_url=f"{settings.public_web_url.rstrip('/')}/subscription/verify",
            metadata={
                "plan": payment.plan_code,
                "months": payment.months,
                "kind": payment.kind,
                "user_id": str(user.id),
            },
        )
    except PaystackError as exc:
        payment.status = "failed"
        payment.gateway_response = "could not start checkout"
        session.commit()
        raise ServiceUnavailableError(
            "Could not start the payment. Try again in a moment.", code="payment_unavailable"
        ) from exc
    return Checkout(payment.reference, checkout.authorization_url, payment.amount_kobo)


# ---------------------------------------------------------------- upgrades


@dataclass(frozen=True)
class UpgradeQuote:
    amount_kobo: int
    days_left: int
    from_plan: Plan
    to_plan: Plan


def quote_upgrade(
    session: Session, user: User, plan_code: str, settings: Settings, now: datetime | None = None
) -> UpgradeQuote:
    """What it costs to move a running institution plan to a bigger one, for the rest of the period.

    The price is the monthly difference, scaled to the time left (rounded up to the next kobo).
    The period end does not move. Only bigger plans qualify; moving to a smaller one waits for the
    end of the period (see `_check_plan_change`).
    """
    now = now or utcnow()
    new = get_plan(plan_code)
    inst = owned_institution(session, user)
    sub = institution_subscription(session, inst.id) if inst else None
    cur = get_plan(sub.plan_code) if sub else None
    if new is None or new.kind != "institution" or inst is None or sub is None or cur is None:
        raise InvalidPlanError(
            "An upgrade needs a running institution plan.", code="not_upgradable"
        )
    if not _live(sub, now):
        raise ConflictError("Your plan has ended. Renew it instead.", code="plan_ended")
    if (new.seats or 0) <= (cur.seats or 0):
        raise ConflictError("Pick a plan with more people to upgrade.", code="not_an_upgrade")
    left = ensure_utc(sub.current_period_end) - now
    if left < timedelta(days=1):
        raise ConflictError(
            "Your plan ends in under a day. Renew it on the bigger plan instead.", code="too_late"
        )
    period = timedelta(days=settings.billing_period_days).total_seconds()
    amount = math.ceil((new.monthly_kobo - cur.monthly_kobo) * left.total_seconds() / period)
    return UpgradeQuote(max(amount, 100), left.days, cur, new)


def create_upgrade_checkout(
    session: Session,
    *,
    user: User,
    plan_code: str,
    client: PaystackClient,
    settings: Settings,
) -> Checkout:
    q = quote_upgrade(session, user, plan_code, settings)
    inst = owned_institution(session, user)
    assert inst is not None
    payment = Payment(
        reference=f"pp_{secrets.token_hex(14)}",
        user_id=user.id,
        plan_code=q.to_plan.code,
        months=0,
        amount_kobo=q.amount_kobo,
        currency=CURRENCY,
        institution_name=inst.name,
        institution_id=inst.id,
        kind="upgrade",
        from_plan_code=q.from_plan.code,
    )
    return _start_payment(session, payment, user, client, settings)


def _active_seat_count(session: Session, institution_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(InstitutionSeat)
            .join(User, User.id == InstitutionSeat.user_id)
            .where(InstitutionSeat.institution_id == institution_id, User.is_active.is_(True))
        )
        or 0
    )


def _check_plan_change(session: Session, inst: Institution, plan: Plan, now: datetime) -> None:
    sub = institution_subscription(session, inst.id)
    if sub is None or sub.plan_code == plan.code:
        return
    if _live(sub, now):
        raise ConflictError(
            "Your current plan is still running. You can move to a smaller plan after "
            f"{ensure_utc(sub.current_period_end):%d %B %Y}, upgrade to a bigger one now, or renew "
            "the same plan.",
            code="plan_change_not_allowed",
        )
    assert plan.seats is not None
    used = _active_seat_count(session, inst.id)
    if used > plan.seats:
        raise ConflictError(
            f"{used} logins are active but this plan has {plan.seats}. "
            "Close some logins first, then pay.",
            code="too_many_active_seats",
        )


# ---------------------------------------------------------------- settling


def _new_institution_code(session: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        if session.scalar(select(Institution.id).where(Institution.code == code)) is None:
            return code
    raise RuntimeError("could not allocate an institution code")


def _extend(sub: Subscription, plan: Plan, months: int, settings: Settings, now: datetime) -> None:
    """Add paid time. A trial or lapsed plan restarts from now; a running paid plan is extended."""
    running = ensure_utc(sub.current_period_end) > now and sub.plan_code != TRIAL_PLAN
    base = ensure_utc(sub.current_period_end) if running else now
    sub.current_period_end = base + timedelta(days=settings.billing_period_days * months)
    sub.plan_code = plan.code
    sub.seats = plan.seats


def grant(
    session: Session,
    *,
    payment: Payment,
    settings: Settings,
    now: datetime,
) -> None:
    """Apply a successful payment. Caller commits."""
    plan = get_plan(payment.plan_code)
    assert plan is not None
    if payment.kind == "upgrade":
        # Same period end, bigger plan. (If the period ran out while the payment was in flight the
        # plan still changes but there is no time to use it; an administrator can fix that.)
        sub = (
            institution_subscription(session, payment.institution_id)
            if payment.institution_id
            else None
        )
        if sub is None:
            raise ConflictError("The plan to upgrade no longer exists.", code="not_upgradable")
        if not _live(sub, now):
            logger.error("Upgrade %s settled after the plan ended", payment.reference)
        sub.plan_code = plan.code
        sub.seats = plan.seats
        return
    if plan.kind == "individual":
        sub = _subscription_for_user(session, payment.user_id)
        if sub is None:
            sub = Subscription(user_id=payment.user_id, plan_code=plan.code, current_period_end=now)
            session.add(sub)
        _extend(sub, plan, payment.months, settings, now)
        return

    inst = session.get(Institution, payment.institution_id) if payment.institution_id else None
    if inst is None:
        inst = Institution(
            name=payment.institution_name or "Institution",
            code=_new_institution_code(session),
            owner_id=payment.user_id,
        )
        session.add(inst)
        session.flush()
        payment.institution_id = inst.id
    sub = institution_subscription(session, inst.id)
    if sub is None:
        sub = Subscription(institution_id=inst.id, plan_code=plan.code, current_period_end=now)
        session.add(sub)
    _extend(sub, plan, payment.months, settings, now)


def settle_payment(
    session: Session,
    *,
    reference: str,
    client: PaystackClient,
    settings: Settings,
    user_id: uuid.UUID | None = None,
    sender: EmailSender | None = None,
) -> Payment:
    """Ask Paystack what happened to `reference` and update our records. Safe to call twice.

    `user_id` restricts the lookup to that person's payments (the return page); the webhook
    passes None.
    """
    stmt = select(Payment).where(Payment.reference == reference).with_for_update()
    payment = session.scalar(stmt)
    if payment is None or (user_id is not None and payment.user_id != user_id):
        raise NotFoundError("Payment not found.", code="payment_not_found")
    if payment.status in {"success", "refunded"}:
        return payment
    newly_paid = False
    try:
        tx = client.verify(reference)
    except PaystackError as exc:
        session.rollback()
        raise ServiceUnavailableError(
            "Could not confirm the payment yet. Try again in a moment.", code="payment_unavailable"
        ) from exc

    if tx.status == "success":
        if tx.amount_kobo != payment.amount_kobo or tx.currency != payment.currency:
            logger.error(
                "Payment %s amount mismatch: paid %s %s, expected %s %s",
                reference,
                tx.amount_kobo,
                tx.currency,
                payment.amount_kobo,
                payment.currency,
            )
            payment.status = "failed"
            payment.gateway_response = "amount mismatch"
        else:
            now = utcnow()
            grant(session, payment=payment, settings=settings, now=now)
            payment.status = "success"
            payment.paid_at = now
            payment.gateway_response = tx.gateway_response
            newly_paid = True
            if payment.save_card:
                remember_card(session, payment.user_id, tx.authorization)
    elif tx.status in {"failed", "reversed"}:
        payment.status = "failed"
        payment.gateway_response = tx.gateway_response
    # abandoned / ongoing / pending: leave it pending; the person may still complete it.
    session.commit()
    if newly_paid and sender is not None:
        _send_receipt(session, sender, payment, settings)
    return payment


def admin_grant(
    session: Session,
    *,
    user: User,
    plan_code: str,
    months: int,
    institution_name: str | None,
    settings: Settings,
) -> Payment:
    """Record a payment made outside Paystack (bank transfer, cash) and grant its access."""
    plan = get_plan(plan_code)
    if plan is None:
        raise InvalidPlanError("That plan does not exist.")
    if not 1 <= months <= MAX_MONTHS:
        raise InvalidPlanError(f"Choose between 1 and {MAX_MONTHS} months.")
    inst = owned_institution(session, user) if plan.kind == "institution" else None
    name = inst.name if inst else _clean_name(institution_name)
    if plan.kind == "institution" and name is None:
        raise InvalidPlanError("Enter the institution's name.", code="institution_name_required")
    if inst is not None:
        _check_plan_change(session, inst, plan, utcnow())
    now = utcnow()
    payment = Payment(
        reference=f"manual_{secrets.token_hex(10)}",
        user_id=user.id,
        plan_code=plan.code,
        months=months,
        amount_kobo=plan.monthly_kobo * months,
        currency=CURRENCY,
        status="success",
        paid_at=now,
        institution_name=name,
        institution_id=inst.id if inst else None,
        gateway_response="recorded by an administrator",
    )
    session.add(payment)
    grant(session, payment=payment, settings=settings, now=now)
    session.commit()
    return payment


def list_payments(session: Session, user: User, limit: int = 20) -> list[Payment]:
    return list(
        session.scalars(
            select(Payment)
            .where(Payment.user_id == user.id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
    )


def recent_payments(session: Session, limit: int = 30) -> list[tuple[Payment, User]]:
    """Newest payments from everyone, with who made them. For administrators."""
    rows = session.execute(
        select(Payment, User)
        .join(User, User.id == Payment.user_id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
    ).all()
    return [(p, u) for p, u in rows]


# ---------------------------------------------------------------- receipts and refunds


def _plan_label(payment: Payment) -> str:
    plan = get_plan(payment.plan_code)
    name = plan.name if plan else payment.plan_code
    if payment.kind == "upgrade":
        return f"Upgrade to {name}"
    if payment.kind == "renewal":
        return (
            f"Automatic renewal: {name}, {payment.months} month{'' if payment.months == 1 else 's'}"
        )
    return f"{name}, {payment.months} month{'' if payment.months == 1 else 's'}"


def _naira(kobo: int) -> str:
    whole, rest = divmod(kobo, 100)
    return f"NGN {whole:,}" + (f".{rest:02d}" if rest else "")


def _send_receipt(
    session: Session, sender: EmailSender, payment: Payment, settings: Settings
) -> None:
    """A receipt by email. Never lets an email problem undo a payment that already went through."""
    user = session.get(User, payment.user_id)
    if user is None or not user.email:
        return
    sub = (
        institution_subscription(session, payment.institution_id)
        if payment.institution_id
        else _subscription_for_user(session, user.id)
    )
    until = f"{ensure_utc(sub.current_period_end):%d %B %Y}" if sub else "-"
    web = settings.public_web_url.rstrip("/")
    card = session.scalar(select(SavedCard).where(SavedCard.user_id == user.id))
    renewal_note = (
        f"Your plan renews by itself and charges the card ending {card.last4}. "
        f"Turn that off any time: {web}/subscription\n\n"
        if card is not None and card.auto_renew and settings.auto_renewal_enabled
        else "Plans do not renew by themselves. "
    )
    next_step = (
        f"Create logins for your people: {web}/institution"
        if payment.plan_code.startswith("institution")
        else f"Start here: {web}/dashboard"
    )
    try:
        sender.send(
            EmailMessage(
                to=user.email,
                subject=f"Receipt: {_plan_label(payment)}",
                body=(
                    "Thank you. Your payment was received.\n\n"
                    f"Item:       {_plan_label(payment)}\n"
                    f"Amount:     {_naira(payment.amount_kobo)}\n"
                    f"Paid on:    {payment.paid_at:%d %B %Y}\n"
                    f"Reference:  {payment.reference}\n"
                    f"Access until: {until}\n\n"
                    f"{next_step}\n\n"
                    f"{renewal_note}Keep this email as your receipt."
                ),
            )
        )
    except AppError:
        logger.warning("Could not send a receipt for %s", payment.reference)


def reverse_payment(
    session: Session,
    payment: Payment,
    settings: Settings,
    now: datetime | None = None,
    amount_kobo: int | None = None,
    cut_days: int | None = None,
) -> None:
    """Take back access after a refund. Caller commits. The money itself is refunded in the
    Paystack dashboard; this only fixes our side.

    Without `amount_kobo` the rest of the payment is refunded: a purchase loses the months it
    bought that were not already taken back (never going earlier than now), and an upgrade goes
    back to the plan it came from, as long as the institution has no more active logins than
    that allows.

    With `amount_kobo` smaller than what is left, it is a partial refund of a purchase or
    renewal: `cut_days` of access are taken back (default: the same share of the days that the
    amount is of the price). The payment stays "paid" until the whole amount has been refunded.
    Upgrades can only be refunded in full, because a plan change cannot be half undone.
    """
    now = now or utcnow()
    if payment.status != "success":
        raise ConflictError("Only a paid payment can be refunded.", code="not_refundable")
    plan = get_plan(payment.plan_code)
    assert plan is not None
    left_kobo = payment.amount_kobo - payment.refunded_kobo
    amount = left_kobo if amount_kobo is None else amount_kobo
    if amount <= 0 or amount > left_kobo:
        raise ConflictError(
            f"The amount must be between 1 and {left_kobo} kobo (what is left to refund).",
            code="bad_refund_amount",
        )
    partial = amount < left_kobo
    total_days = settings.billing_period_days * payment.months
    days_left = total_days - payment.refunded_days
    if partial:
        if payment.kind == "upgrade":
            raise ConflictError(
                "An upgrade can only be refunded in full.", code="not_refundable_partly"
            )
        days = round(total_days * amount / payment.amount_kobo) if cut_days is None else cut_days
        if not 0 <= days <= days_left:
            raise ConflictError(
                f"Days to take back must be between 0 and {days_left}.", code="bad_refund_days"
            )
    else:
        if cut_days is not None and payment.kind != "upgrade" and not 0 <= cut_days <= days_left:
            raise ConflictError(
                f"Days to take back must be between 0 and {days_left}.", code="bad_refund_days"
            )
        days = days_left if cut_days is None or payment.kind == "upgrade" else cut_days
    if payment.institution_id:
        sub = institution_subscription(session, payment.institution_id)
    else:
        sub = _subscription_for_user(session, payment.user_id)
    if sub is not None:
        if payment.kind == "upgrade":
            old = get_plan(payment.from_plan_code or "")
            if old is None:
                raise ConflictError("The earlier plan is unknown.", code="not_refundable")
            used = (
                _active_seat_count(session, payment.institution_id) if payment.institution_id else 0
            )
            if used > (old.seats or 0):
                raise ConflictError(
                    f"{used} logins are active but the earlier plan allows {old.seats}. "
                    "Close some logins first.",
                    code="too_many_active_seats",
                )
            sub.plan_code, sub.seats = old.code, old.seats
        elif days:
            cut = timedelta(days=days)
            sub.current_period_end = max(now, ensure_utc(sub.current_period_end) - cut)
    payment.refunded_kobo += amount
    if payment.kind != "upgrade":
        payment.refunded_days += days
    if not partial:
        payment.status = "refunded"
        payment.refunded_at = now


@dataclass(frozen=True)
class RefundCheck:
    days_since_paid: int
    window_days: int  # 0 = no limit
    outside_window: bool
    prior_refunds: int  # this person's other payments that already had money refunded
    repeat: bool  # prior_refunds has reached REPEAT_REFUNDS

    @property
    def needs_override(self) -> bool:
        return self.outside_window or self.repeat


REPEAT_REFUNDS = 2  # this many earlier refunds makes a new one need a second look


def refund_check(
    session: Session, payment: Payment, settings: Settings, now: datetime | None = None
) -> RefundCheck:
    """Is this refund unusual? Late, or from someone who has been refunded before."""
    now = now or utcnow()
    paid = ensure_utc(payment.paid_at or payment.created_at)
    days = max(0, (now - paid).days)
    window = settings.refund_window_days
    prior = (
        session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.user_id == payment.user_id,
                Payment.id != payment.id,
                Payment.refunded_kobo > 0,
            )
        )
        or 0
    )
    return RefundCheck(
        days_since_paid=days,
        window_days=window,
        outside_window=window > 0 and days > window,
        prior_refunds=prior,
        repeat=prior >= REPEAT_REFUNDS,
    )


# ---------------------------------------------------------------- saved card / auto-renewal

MAX_FAILURES = 3  # failed renewals in a row before automatic renewal switches itself off


def get_card(session: Session, user_id: uuid.UUID) -> SavedCard | None:
    return session.scalar(select(SavedCard).where(SavedCard.user_id == user_id))


def remember_card(session: Session, user_id: uuid.UUID, auth: CardAuthorization | None) -> bool:
    """Keep the card that just paid, if Paystack says it can be charged again. Caller commits.

    Only a card payment can be reused; a bank transfer or USSD payment cannot, and then nothing
    is saved (the person is told on the Subscription page).
    """
    if auth is None or not auth.reusable or auth.channel != "card" or not auth.code:
        return False
    card = get_card(session, user_id)
    if card is None:
        card = SavedCard(user_id=user_id, authorization_code="")
        session.add(card)
    card.authorization_code = crypto.encrypt(auth.code)
    card.brand, card.last4 = auth.brand, auth.last4
    card.exp_month, card.exp_year = auth.exp_month, auth.exp_year
    card.auto_renew = True
    card.failures = 0
    return True


def set_auto_renew(session: Session, user: User, enabled: bool) -> SavedCard | None:
    card = get_card(session, user.id)
    if enabled and card is None:
        raise ConflictError(
            'Pay once by card with "Renew automatically" ticked first.', code="no_saved_card"
        )
    if card is not None:
        card.auto_renew = enabled
        if enabled:
            card.failures = 0
        session.commit()
    return card


def delete_card(session: Session, user: User) -> None:
    card = get_card(session, user.id)
    if card is not None:
        session.delete(card)
        session.commit()
